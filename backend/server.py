import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.amazon_scraper import AmazonExtractor
from backend.pl_detector import evaluate_private_label
from backend.linkedin_finder import find_decision_maker
from backend.brand_finder import find_brand_website_and_contacts
from backend.seller_checker import matches_region_filter, is_seller_allowed
from backend.brand_health_auditor import classify_brand_persona, generate_growth_strategy_and_pitch
from backend.exporter import export_to_csv_bytes, export_to_excel_bytes

app = FastAPI(
    title="Amazon Private Label & LinkedIn Extractor API",
    description="Extracts Private Label brands, evaluates buy box and multi-seller listings, and discovers founders on LinkedIn.",
    version="1.2.0"
)

# Enable CORS for browser extensions and local dashboards
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

JOBS: Dict[str, Dict[str, Any]] = {}

class ExtractRequest(BaseModel):
    query: str = Field(..., description="Amazon search keyword or category URL")
    marketplace: str = Field(default="amazon.com", description="Amazon domain (e.g. amazon.com, amazon.co.uk)")
    max_pages: int = Field(default=3, ge=1, le=10, description="Number of pages to crawl (1 to 10)")
    max_reviews: Optional[int] = Field(default=None, description="Optional maximum review count limit, e.g. 100")
    region_filter: Optional[str] = Field(default=None, description="Optional seller region filter, e.g. US, NON_CN, CN, UK_EU")
    exclude_countries: Optional[Any] = Field(default=None, description="Optional list or comma-separated string of countries to exclude, e.g. ['CN', 'HK']")
    check_all_brand_products_under_100: bool = Field(default=True, description="Verify that ALL products from the brand have < max_reviews")
    require_contactable: bool = Field(default=False, description="Filter out brands with zero contact channels")
    direct_contact_only: bool = Field(default=False, description="Filter for direct founder/decision-maker contacts only")
    persona_filter: Optional[str] = Field(default=None, description="Filter by brand persona: NEW_LAUNCH, STAGNANT_VETERAN, DISTRESSED")

class DirectProductScanItem(BaseModel):
    asin: str
    title: Optional[str] = ""
    brand: Optional[str] = ""
    price: Optional[str] = ""
    reviews: Optional[int] = 0
    product_url: Optional[str] = ""

class ActiveTabScanRequest(BaseModel):
    products: List[DirectProductScanItem]
    marketplace: Optional[str] = "amazon.com"
    max_reviews: Optional[int] = Field(default=None, description="Optional maximum review count limit, e.g. 100")
    region_filter: Optional[str] = Field(default=None, description="Optional seller region filter, e.g. US, NON_CN, CN, UK_EU")
    exclude_countries: Optional[Any] = Field(default=None, description="Optional countries to exclude, e.g. ['CN', 'HK']")
    check_all_brand_products_under_100: bool = Field(default=True, description="Verify that ALL products from the brand have < max_reviews")
    require_contactable: bool = Field(default=False, description="Filter out brands with zero contact channels")
    direct_contact_only: bool = Field(default=False, description="Filter for direct founder/decision-maker contacts only")
    persona_filter: Optional[str] = Field(default=None, description="Filter by brand persona: NEW_LAUNCH, STAGNANT_VETERAN, DISTRESSED")

class BrandAsinAuditRequest(BaseModel):
    asin_or_url: str = Field(..., description="Amazon ASIN (e.g. B09XYZ1234) or product URL")
    marketplace: Optional[str] = Field(default="amazon.com", description="Amazon marketplace domain")
    check_all_brand_products_under_100: bool = Field(default=True, description="Verify if all brand SKUs have < 100 reviews")
    max_reviews: int = Field(default=100, description="Review threshold cap")

def background_crawl_worker(
    job_id: str,
    query: str,
    marketplace: str,
    max_pages: int,
    max_reviews: Optional[int] = None,
    region_filter: Optional[str] = None,
    exclude_countries: Optional[Any] = None,
    check_all_brand_products_under_100: bool = True,
    require_contactable: bool = False,
    direct_contact_only: bool = False,
    persona_filter: Optional[str] = None
):
    """Worker function that runs the extraction job in background."""
    job = JOBS.get(job_id)
    if not job:
        return

    job["status"] = "running"
    if "activity_log" not in job:
        job["activity_log"] = []

    def progress_callback(update: Dict[str, Any]):
        job["current_status"] = update.get("status", "")
        msg = update.get("message", "")
        job["current_message"] = msg
        if "current_page" in update:
            job["current_page"] = update["current_page"]
        if "max_pages" in update:
            job["max_pages"] = update["max_pages"]
        if "total_scanned" in update:
            job["total_scanned"] = update["total_scanned"]
        if "record" in update:
            job["records"].append(update["record"])
        if msg:
            timestamp = datetime.now().strftime("%H:%M:%S")
            job["activity_log"].append(f"[{timestamp}] {msg}")
            if len(job["activity_log"]) > 30:
                job["activity_log"] = job["activity_log"][-30:]

    def should_stop() -> bool:
        return job.get("should_stop", False)

    try:
        extractor = AmazonExtractor(marketplace=marketplace, delay_between_requests=0.5)
        results = extractor.run_pipeline(
            query=query,
            max_pages=max_pages,
            max_reviews=max_reviews,
            region_filter=region_filter,
            exclude_countries=exclude_countries,
            check_all_brand_products_under_100=check_all_brand_products_under_100,
            require_contactable=require_contactable,
            direct_contact_only=direct_contact_only,
            persona_filter=persona_filter,
            progress_callback=progress_callback,
            should_stop_check=should_stop
        )
        if job.get("should_stop", False):
            job["status"] = "stopped"
            job["current_message"] = f"Extraction stopped by user. Found {len(results)} PL brands."
        else:
            job["status"] = "completed"
            job["records"] = results
            job["current_message"] = f"Extraction complete! Found {len(results)} unique Private Label brands."
    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)
        job["current_message"] = f"Extraction encountered an error: {str(e)}"

@app.get("/api/health")
def health_check():
    return {
        "status": "online",
        "service": "Amazon Private Label & Decision Maker Extractor",
        "active_jobs_count": len([j for j in JOBS.values() if j.get("status") == "running"])
    }

@app.post("/api/extract")
def start_extraction(req: ExtractRequest, background_tasks: BackgroundTasks):
    # Cancel any previous running jobs to avoid competing crawlers and IP rate limits
    for old_id, old_job in list(JOBS.items()):
        if old_job.get("status") in ["running", "pending"]:
            old_job["should_stop"] = True
            old_job["status"] = "stopped"

    job_id = str(uuid.uuid4())[:8]
    JOBS[job_id] = {
        "job_id": job_id,
        "query": req.query,
        "marketplace": req.marketplace,
        "max_pages": req.max_pages,
        "max_reviews": req.max_reviews,
        "region_filter": req.region_filter,
        "exclude_countries": req.exclude_countries,
        "status": "pending",
        "current_page": 1,
        "max_pages": req.max_pages,
        "total_scanned": 0,
        "current_message": "Initializing multi-page crawler...",
        "activity_log": [],
        "records": [],
        "should_stop": False,
        "error": None
    }

    background_tasks.add_task(
        background_crawl_worker,
        job_id,
        req.query,
        req.marketplace,
        req.max_pages,
        req.max_reviews,
        req.region_filter,
        req.exclude_countries,
        req.check_all_brand_products_under_100,
        req.require_contactable,
        req.direct_contact_only,
        req.persona_filter
    )

    return {
        "job_id": job_id,
        "status": "started",
        "message": f"Started crawl for '{req.query}' up to {req.max_pages} pages."
    }

@app.get("/api/job/{job_id}")
def get_job_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@app.post("/api/job/{job_id}/stop")
def stop_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job["should_stop"] = True
    job["current_message"] = "Stopping extraction..."
    return {"status": "stopping"}

@app.post("/api/audit-brand-asin")
def audit_brand_asin(req: BrandAsinAuditRequest):
    """
    Executes a comprehensive deep audit on a specific ASIN or Brand:
    - ASIN health issues, Buy Box status, suppression, return badges
    - Seller information, registered entity, address, Chinese seller check
    - Full Brand Catalog check (<100 reviews across all brand products)
    - Decision maker / founder discovery on LinkedIn
    - Brand website, direct personal vs CS email, phone, social profiles
    - Brand persona classification & tailored cold outreach pitch hook
    """
    extractor = AmazonExtractor(marketplace=req.marketplace or "amazon.com", delay_between_requests=0.3)
    result = extractor.audit_brand_by_asin(
        asin_or_url=req.asin_or_url,
        check_all_brand_products_under_100=req.check_all_brand_products_under_100,
        max_reviews=req.max_reviews
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Audit failed"))
    return result

@app.post("/api/analyze-active-tab")
def analyze_active_tab(req: ActiveTabScanRequest):
    """
    Process products sent directly from the Chrome extension active tab:
    - Applies strict Negation of wholesale, Amazon 1P, and megabrands
    - Checks buy box, seller roster, Brand Store, and A+ content
    - Deduplicates brands
    - Finds founder and LinkedIn profile
    """
    extractor = AmazonExtractor(marketplace=req.marketplace or "amazon.com", delay_between_requests=0.2)
    seen_brands = set()
    pl_records = []

    for item in req.products:
        asin = item.asin
        if not asin:
            continue

        details = extractor.inspect_asin_details(asin)
        brand_name = details.get("brand") or item.brand or ""

        if not brand_name or brand_name.lower() in ["unknown", "generic", "brand", "null", "none", "n/a", "unbranded"] or len(brand_name) < 2:
            continue

        norm_b = brand_name.lower().strip()
        if norm_b in seen_brands:
            continue

        # Strict PL evaluation with negation
        pl_eval = evaluate_private_label(
            brand_name=brand_name,
            buybox_seller=details.get("buybox_seller", ""),
            all_sellers=details.get("all_sellers", []),
            has_brand_store=details.get("has_brand_store", False),
            has_aplus_content=details.get("has_aplus", False),
            total_offers_count=details.get("total_offers", 1)
        )

        if pl_eval["is_private_label"]:
            prod_reviews = details.get("reviews") or item.reviews or 0
            if req.max_reviews is not None and prod_reviews >= req.max_reviews:
                continue

            seller_country = details.get("seller_country", "Unknown")
            if not is_seller_allowed(seller_country, region_filter=req.region_filter, exclude_countries=req.exclude_countries):
                continue

            # Full Brand Catalog Audit: Verify ALL other products of this brand have < review_cap
            catalog_max_rev = prod_reviews
            catalog_count = 1
            if req.check_all_brand_products_under_100:
                review_cap = req.max_reviews if req.max_reviews is not None else 100
                catalog_check = extractor.check_brand_catalog_reviews(
                    brand_name=brand_name,
                    current_asin=asin,
                    max_reviews=review_cap
                )
                if not catalog_check.get("all_under_threshold", True):
                    seen_brands.add(norm_b)
                    continue
                catalog_max_rev = max(prod_reviews, catalog_check.get("max_brand_reviews", 0))
                catalog_count = catalog_check.get("total_brand_products_found", 1)

            seen_brands.add(norm_b)
            # Find decision maker and brand website contacts
            decision_maker = find_decision_maker(brand_name)
            founder_name = decision_maker.get("founder_name", "Not Found")
            linkedin_url = decision_maker.get("linkedin_url", "Not Found")
            brand_contacts = find_brand_website_and_contacts(brand_name, founder_name=founder_name)

            personal_em = brand_contacts.get("personal_email", "Not Found")
            cs_em = brand_contacts.get("cs_email", "Not Found")
            web_ph = brand_contacts.get("phone", "Not Found")
            seller_em = details.get("seller_email", "Not Found")
            seller_ph = details.get("seller_phone", "Not Found")

            if seller_em != "Not Found" and cs_em == "Not Found":
                cs_em = seller_em

            if personal_em != "Not Found":
                final_email = personal_em
                email_type = "Direct Personal"
            elif cs_em != "Not Found":
                final_email = cs_em
                email_type = "Customer Support"
            elif seller_em != "Not Found":
                final_email = seller_em
                email_type = "Customer Support"
            else:
                final_email = "Not Found"
                email_type = "None"

            final_phone = web_ph if web_ph != "Not Found" else seller_ph

            has_direct_lead = (personal_em != "Not Found") or (linkedin_url != "Not Found" and "linkedin.com/in/" in linkedin_url)
            has_any_contact = has_direct_lead or (final_email != "Not Found") or (final_phone != "Not Found")

            if has_direct_lead:
                contact_quality = "⭐ Direct Decision Maker"
            elif has_any_contact:
                contact_quality = "📧 General / Support Only"
            else:
                contact_quality = "❌ Uncontactable"

            if req.require_contactable and not has_any_contact:
                continue
            if req.direct_contact_only and not has_direct_lead:
                continue

            health_issues = details.get("health_issues", [])
            persona_title, persona_badge = classify_brand_persona(
                age_months=details.get("age_months"),
                reviews=prod_reviews,
                catalog_health_issues=health_issues,
                has_aplus=details.get("has_aplus", False)
            )

            if req.persona_filter and req.persona_filter.upper() != "ALL":
                pf = req.persona_filter.upper()
                if pf in ["NEW_LAUNCH", "NEW"] and "New Launch" not in persona_badge:
                    continue
                elif pf in ["STAGNANT_VETERAN", "VETERAN", "STAGNANT"] and "Stagnant Veteran" not in persona_badge:
                    continue
                elif pf in ["DISTRESSED", "PROBLEMS"] and "Distressed" not in persona_badge:
                    continue

            prod_rating = details.get("rating", 0.0)
            strategy = generate_growth_strategy_and_pitch(
                brand_name=brand_name,
                persona_badge=persona_badge,
                primary_asin=asin,
                reviews=prod_reviews,
                rating=prod_rating,
                age_months=details.get("age_months"),
                date_first_available=details.get("date_first_available", "Not Listed"),
                health_issues=health_issues,
                has_aplus=details.get("has_aplus", False),
                has_video=details.get("has_video", False),
                founder_name=founder_name
            )

            record = {
                "asin": asin,
                "brand_name": brand_name,
                "brand_persona": persona_badge,
                "brand_persona_title": persona_title,
                "contact_quality": contact_quality,
                "email": final_email,
                "email_type": email_type,
                "personal_email": personal_em,
                "cs_email": cs_em,
                "phone": final_phone,
                "social_summary": brand_contacts.get("social_summary", "Not Found"),
                "website": brand_contacts.get("website", "Not Found"),
                "founder_name": founder_name,
                "linkedin_url": linkedin_url,
                "decision_maker_role": decision_maker.get("role_title", ""),
                "date_first_available": details.get("date_first_available", "Not Listed"),
                "brand_age_months": details.get("age_months") or "Unknown",
                "catalog_health_summary": "; ".join(health_issues) if health_issues else "Healthy / No Critical Listing Alerts",
                "is_suppressed": details.get("is_suppressed", False),
                "is_buybox_suppressed": details.get("is_buybox_suppressed", False),
                "has_frequently_returned_badge": details.get("has_frequently_returned_badge", False),
                "bsr": details.get("bsr", "Not Ranked"),
                "growth_pitch_hook": strategy.get("pitch_hook", ""),
                "growth_strategy_achievable": strategy.get("achievable_milestones", ""),
                "growth_strategy_current": strategy.get("current_stats", ""),
                "reviews": prod_reviews,
                "rating": prod_rating if prod_rating > 0 else "",
                "catalog_max_reviews": catalog_max_rev,
                "catalog_products_count": catalog_count,
                "all_products_under_100": "Yes (Verified <100)" if catalog_max_rev < 100 else f"Max {catalog_max_rev}",
                "matched_seller": pl_eval.get("matched_seller", "") or details.get("buybox_seller", ""),
                "seller_country": details.get("seller_country", "Unknown"),
                "seller_country_display": details.get("seller_country_display", "Unknown"),
                "seller_business_name": details.get("seller_business_name", "Not Available"),
                "seller_address": details.get("seller_address", "Not Available"),
                "seller_id": details.get("seller_id", ""),
                "seller_email": seller_em,
                "seller_phone": seller_ph,
                "seller_bio": details.get("seller_bio", ""),
                "pl_confidence": pl_eval.get("confidence", "High"),
                "seller_match_type": pl_eval.get("seller_match_type", ""),
                "buybox_seller": details.get("buybox_seller", "None"),
                "all_sellers_found": ", ".join(details.get("all_sellers", [])) or details.get("buybox_seller", ""),
                "product_title": item.title or "",
                "price": item.price or "",
                "product_url": item.product_url or f"{extractor.base_url}/dp/{asin}"
            }
            pl_records.append(record)

    return {
        "status": "success",
        "total_scanned": len(req.products),
        "total_pl_found": len(pl_records),
        "records": pl_records
    }

@app.get("/api/export/{job_id}/{fmt}")
def export_job_results(job_id: str, fmt: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    records = job.get("records", [])
    if not records:
        raise HTTPException(status_code=400, detail="No records available to export")

    if fmt.lower() == "xlsx":
        content = export_to_excel_bytes(records)
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=amazon_pl_{job_id}.xlsx"}
        )
    else:
        content = export_to_csv_bytes(records)
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=amazon_pl_{job_id}.csv"}
        )

@app.post("/api/export-direct/{fmt}")
def export_direct_records(fmt: str, records: List[Dict[str, Any]]):
    if not records:
        raise HTTPException(status_code=400, detail="No records provided")

    if fmt.lower() == "xlsx":
        content = export_to_excel_bytes(records)
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=amazon_pl_export.xlsx"}
        )
    else:
        content = export_to_csv_bytes(records)
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=amazon_pl_export.csv"}
        )
