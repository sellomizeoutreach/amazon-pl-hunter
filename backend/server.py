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
from backend.seller_checker import matches_region_filter
from backend.exporter import export_to_csv_bytes, export_to_excel_bytes

app = FastAPI(
    title="Amazon Private Label & LinkedIn Extractor API",
    description="Extracts Private Label brands, evaluates buy box and multi-seller listings, and discovers founders on LinkedIn.",
    version="1.1.0"
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

def background_crawl_worker(job_id: str, query: str, marketplace: str, max_pages: int, max_reviews: Optional[int] = None, region_filter: Optional[str] = None):
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
        req.region_filter
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
            if req.region_filter and not matches_region_filter(seller_country, req.region_filter):
                continue

            seen_brands.add(norm_b)
            # Find decision maker and brand website contacts
            decision_maker = find_decision_maker(brand_name)
            brand_contacts = find_brand_website_and_contacts(brand_name)

            record = {
                "asin": asin,
                "brand_name": brand_name,
                "matched_seller": pl_eval.get("matched_seller", "") or details.get("buybox_seller", ""),
                "seller_country": details.get("seller_country", "Unknown"),
                "seller_country_display": details.get("seller_country_display", "Unknown"),
                "seller_business_name": details.get("seller_business_name", "Not Available"),
                "seller_address": details.get("seller_address", "Not Available"),
                "seller_id": details.get("seller_id", ""),
                "reviews": prod_reviews,
                "website": brand_contacts.get("website", "Not Found"),
                "email": brand_contacts.get("email", "Not Found"),
                "phone": brand_contacts.get("phone", "Not Found"),
                "founder_name": decision_maker.get("founder_name", "Not Found"),
                "linkedin_url": decision_maker.get("linkedin_url", "Not Found"),
                "decision_maker_role": decision_maker.get("role_title", ""),
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
