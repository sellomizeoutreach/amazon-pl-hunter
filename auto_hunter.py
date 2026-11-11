#!/usr/bin/env python3
"""
Automated Amazon Private Label Lead Hunter & Emailer
---------------------------------------------------
Runs headless automated lead discovery across an AUTO-GENERATED keyword list:
- Keywords are discovered automatically every run from Amazon Best Sellers,
  Amazon Movers & Shakers, and DuckDuckGo trending niche search — no manual
  keyword input required. Keywords rotate daily for fresh niche coverage.
- Verifies Private Label ownership
- Audits full brand catalog: only keeps brands where ALL products have < 100 reviews
- Strict non-China origin filter (US/UK/EU/CA)
- Listing health & problem detection (suppression, return badges, star rating)
- Brand Persona segmentation (🚀 New Launch, 📉 Stagnant Veteran, ⚠️ Distressed)
- Strict Contactability Gate: skips leads with no reachable contact channels
- Extracts Amazon seller customer service phone & email
- Enriches with brand website, personal vs CS emails, and direct phone
- Discovers LinkedIn founder / CEO
- Tailors cold pitch outreach hooks and growth strategies
- Deduplicates leads across historical runs
- Dispatches formatted HTML summary email with CSV/Excel attachments
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime
from typing import List, Dict, Any, Set

# Ensure root directory is in sys.path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from backend.amazon_scraper import AmazonExtractor
from backend.auto_mailer import send_leads_email, get_email_config
from backend.keyword_generator import generate_keywords

SEEN_LEADS_FILE = os.path.join(ROOT_DIR, "data", "seen_leads.json")

def load_seen_leads() -> Set[str]:
    """Loads historical brand names to avoid duplicate outreach."""
    os.makedirs(os.path.dirname(SEEN_LEADS_FILE), exist_ok=True)
    if os.path.exists(SEEN_LEADS_FILE):
        try:
            with open(SEEN_LEADS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data)
        except Exception:
            return set()
    return set()

def save_seen_leads(seen: Set[str]):
    """Persists historical brand names to disk."""
    os.makedirs(os.path.dirname(SEEN_LEADS_FILE), exist_ok=True)
    try:
        with open(SEEN_LEADS_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(list(seen)), f, indent=2)
    except Exception as e:
        print(f"Notice saving seen leads: {e}")

def run_auto_hunt(
    max_pages_per_kw: int = 2,
    marketplace: str = "amazon.com",
    region_filter: str = "NON_CN",
    exclude_countries: List[str] = None,
    require_contactable: bool = True,
    direct_contact_only: bool = False,
    persona_filter: str = None,
    send_email: bool = True,
    delay: float = 0.5,
    refresh_keywords: bool = False,
):
    print("=" * 70)
    print("🚀 STARTING AUTOMATED AMAZON PRIVATE LABEL HUNTER")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Marketplace: {marketplace} | Max Pages/Keyword: {max_pages_per_kw}")
    print(f"Region: {region_filter} (Non-China) | Strict Catalog Audit: All SKUs < 100 Revs")
    print(f"Contact Gate: {'Require Contactable (Skip No-Contact Leads)' if require_contactable else 'Include All'}")
    if direct_contact_only:
        print("Contact Filter: ⭐ Direct Founder / Executive Contacts Only")
    if persona_filter:
        print(f"Persona Filter: {persona_filter}")
    print("=" * 70)

    if exclude_countries is None:
        exclude_countries = ["CN", "HK"]

    # --- AUTO-GENERATE KEYWORDS (no manual input required) ---
    print("\n[Step 1/6] Auto-generating keyword list from Amazon BSR, Movers & Shakers, and trending search...")
    keywords = generate_keywords(
        marketplace=marketplace,
        target_count=30,
        use_cache=not refresh_keywords,
        force_refresh=refresh_keywords,
        include_seeds=True,
        verbose=True,
    )
    seen_brands = load_seen_leads()
    print(f"[Step 1/6] Done. {len(keywords)} keywords ready. Historical deduplication DB: {len(seen_brands)} brands.")

    extractor = AmazonExtractor(marketplace=marketplace, delay_between_requests=delay)
    new_discovered_leads = []

    print(f"\n[Step 2/6] Beginning lead hunt across {len(keywords)} keyword niches...\n")
    for idx, kw in enumerate(keywords, 1):
        print(f"\n[{idx}/{len(keywords)}] 🔍 Hunting Keyword: '{kw}'...")
        try:
            results = extractor.run_pipeline(
                query=kw,
                max_pages=max_pages_per_kw,
                max_reviews=100,
                region_filter=region_filter,
                exclude_countries=exclude_countries,
                check_all_brand_products_under_100=True,
                require_contactable=require_contactable,
                direct_contact_only=direct_contact_only,
                persona_filter=persona_filter,
                progress_callback=lambda u: print(f"  -> {u.get('message', '')}") if "Verified PL" in u.get('message', '') or "Disqualified" in u.get('message', '') or "Skipped" in u.get('message', '') else None
            )

            for r in results:
                b_norm = (r.get("brand_name") or "").lower().strip()
                if b_norm and b_norm not in seen_brands:
                    seen_brands.add(b_norm)
                    new_discovered_leads.append(r)
                    persona = r.get("brand_persona", "PL Brand")
                    qual = r.get("contact_quality", "")
                    print(f"  ⭐ NEW LEAD SECURED: [{persona}] '{r.get('brand_name')}' | {qual} | Reviews: {r.get('reviews')} | Seller: {r.get('seller_country_display')} | Email: {r.get('email')} | Phone: {r.get('phone')}")

        except Exception as e:
            print(f"  Notice processing '{kw}': {e}")

        # Polite delay between keywords
        time.sleep(2.0)

    # Save updated deduplication database
    save_seen_leads(seen_brands)

    print("\n" + "=" * 70)
    print(f"🎯 HUNT FINISHED! Found {len(new_discovered_leads)} brand-new verified Private Label leads.")
    print("=" * 70)

    if new_discovered_leads:
        # Save a local backup CSV
        out_csv = os.path.join(ROOT_DIR, "data", f"leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        try:
            from backend.exporter import records_to_dataframe
            df = records_to_dataframe(new_discovered_leads)
            df.to_csv(out_csv, index=False, encoding="utf-8-sig")
            print(f"💾 Saved local backup: {out_csv}")
        except Exception as e:
            print(f"Notice saving local CSV: {e}")

        # Send email if enabled
        if send_email:
            cfg = get_email_config()
            if cfg.get("sender_email") and cfg.get("sender_password") and cfg.get("receiver_email"):
                print(f"📧 Dispatching automated report with attachments to {cfg.get('receiver_email')}...")
                ok, msg = send_leads_email(new_discovered_leads, custom_config=cfg)
                if ok:
                    print(f"✅ {msg}")
                else:
                    print(f"❌ Email sending failed: {msg}")
            else:
                print("ℹ️ Email dispatch skipped: Email credentials not configured yet.")
                print("   Set SENDER_EMAIL, SENDER_PASSWORD, and RECEIVER_EMAIL in your environment or email_config.json.")
    else:
        print("No new leads discovered in this cycle (all matching brands were already in historical leads).")

def run_single_asin_audit(
    asin_or_url: str,
    marketplace: str = "amazon.com",
    check_all_brand_products_under_100: bool = True,
    send_email: bool = False
):
    print("=" * 70)
    print("🔍 RUNNING DIRECT ASIN / BRAND FULL AUDIT")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Target: {asin_or_url} | Marketplace: {marketplace}")
    print("=" * 70)

    extractor = AmazonExtractor(marketplace=marketplace)
    res = extractor.audit_brand_by_asin(
        asin_or_url=asin_or_url,
        check_all_brand_products_under_100=check_all_brand_products_under_100,
        progress_callback=lambda u: print(f"  -> {u.get('message', '')}")
    )

    if not res.get("success"):
        print(f"\n❌ Audit failed: {res.get('error')}")
        return

    print("\n" + "=" * 70)
    print(f"🎯 AUDIT COMPLETE FOR BRAND: '{res.get('brand_name')}' (ASIN: {res.get('asin')})")
    print("=" * 70)
    print(f"• Persona:         {res.get('brand_persona')} ({res.get('brand_persona_title')})")
    print(f"• Contact Quality: {res.get('contact_quality')}")
    print(f"• Founder / CEO:   {res.get('founder_name')} | LinkedIn: {res.get('linkedin_url')}")
    print(f"• Primary Email:   {res.get('email')} ({res.get('email_type')})")
    print(f"• Direct Phone:    {res.get('phone')}")
    print(f"• Website:         {res.get('website')}")
    print(f"• Social:          {res.get('social_summary')}")
    print(f"• Seller Entity:   {res.get('seller_business_name')} ({res.get('seller_country_display')})")
    print(f"• Catalog Check:   {res.get('all_products_under_100')} (Max reviews: {res.get('catalog_max_reviews')})")
    print(f"• Listing Health:  {res.get('catalog_health_summary')}")
    print(f"• Rating / BSR:    {res.get('rating')}★ | BSR: {res.get('bsr')}")
    print(f"• Launch Date:     {res.get('date_first_available')} (Age: {res.get('brand_age_months')} mos)")
    print(f"\n--- TAILORED OUTREACH PITCH HOOK ---\n{res.get('growth_pitch_hook')}\n")

    # Save to data directory
    out_csv = os.path.join(ROOT_DIR, "data", f"audit_{res.get('asin')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    try:
        from backend.exporter import records_to_dataframe
        df = records_to_dataframe([res])
        df.to_csv(out_csv, index=False, encoding="utf-8-sig")
        print(f"💾 Saved audit export: {out_csv}")
    except Exception as e:
        print(f"Notice saving CSV: {e}")

    if send_email:
        cfg = get_email_config()
        if cfg.get("sender_email") and cfg.get("sender_password") and cfg.get("receiver_email"):
            print(f"📧 Dispatching audit report to {cfg.get('receiver_email')}...")
            ok, msg = send_leads_email([res], custom_config=cfg)
            if ok:
                print(f"✅ {msg}")
            else:
                print(f"❌ Email sending failed: {msg}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automated Amazon Private Label Hunter")
    parser.add_argument("--asin", type=str, default=None, help="Directly audit a single ASIN or Amazon product URL with all brand SOPs")
    parser.add_argument("--pages", type=int, default=2, help="Max search pages per keyword (default 2)")
    parser.add_argument("--marketplace", type=str, default="amazon.com", help="Amazon marketplace domain")
    parser.add_argument("--allow-uncontactable", action="store_true", help="Include leads even if they have no reachable contact")
    parser.add_argument("--direct-only", action="store_true", help="Only keep leads with direct founder/decision-maker contacts")
    parser.add_argument("--persona", type=str, default=None, choices=["NEW_LAUNCH", "STAGNANT_VETERAN", "DISTRESSED"], help="Filter by specific brand persona")
    parser.add_argument("--no-email", action="store_true", help="Skip sending email report")
    parser.add_argument("--refresh-keywords", action="store_true", help="Force-regenerate the keyword list from Amazon BSR/Movers/DDGS, bypassing today's cache")
    args = parser.parse_args()

    if args.asin:
        run_single_asin_audit(
            asin_or_url=args.asin,
            marketplace=args.marketplace,
            send_email=not args.no_email
        )
    else:
        run_auto_hunt(
            max_pages_per_kw=args.pages,
            marketplace=args.marketplace,
            require_contactable=not args.allow_uncontactable,
            direct_contact_only=args.direct_only,
            persona_filter=args.persona,
            send_email=not args.no_email,
            refresh_keywords=args.refresh_keywords,
        )
