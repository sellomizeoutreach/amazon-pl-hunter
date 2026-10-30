#!/usr/bin/env python3
"""
Automated Amazon Private Label Lead Hunter & Emailer
---------------------------------------------------
Runs headless automated lead discovery across a keyword list:
- Verifies Private Label ownership
- Audits full brand catalog: only keeps brands where ALL products have < 100 reviews
- Strict non-China origin filter (US/UK/EU/CA)
- Extracts Amazon seller customer service phone & email
- Enriches with brand website, website email & phone
- Discovers LinkedIn founder / CEO
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

DEFAULT_KEYWORDS = [
    "silicone kitchen utensils",
    "bamboo drawer organizer",
    "yoga mat non slip",
    "travel packing cubes",
    "posture corrector",
    "pet grooming brush",
    "desk cable management",
    "camping hammock lightweight"
]

SEEN_LEADS_FILE = os.path.join(ROOT_DIR, "data", "seen_leads.json")
KEYWORDS_FILE = os.path.join(ROOT_DIR, "keywords.txt")

def ensure_keywords_file():
    """Ensure keywords.txt exists with default starting niches."""
    if not os.path.exists(KEYWORDS_FILE):
        try:
            with open(KEYWORDS_FILE, "w", encoding="utf-8") as f:
                f.write("\n".join(DEFAULT_KEYWORDS) + "\n")
            print(f"Created default {KEYWORDS_FILE} with {len(DEFAULT_KEYWORDS)} niches.")
        except Exception as e:
            print(f"Notice creating keywords.txt: {e}")

def load_keywords() -> List[str]:
    """Loads search keywords from keywords.txt."""
    ensure_keywords_file()
    keywords = []
    if os.path.exists(KEYWORDS_FILE):
        with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                k = line.strip()
                if k and not k.startswith("#"):
                    keywords.append(k)
    return keywords or DEFAULT_KEYWORDS

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
    send_email: bool = True,
    delay: float = 0.5
):
    print("=" * 70)
    print("🚀 STARTING AUTOMATED AMAZON PRIVATE LABEL HUNTER")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Marketplace: {marketplace} | Max Pages/Keyword: {max_pages_per_kw}")
    print(f"Region: {region_filter} (Non-China) | Strict Catalog Audit: All SKUs < 100 Revs")
    print("=" * 70)

    if exclude_countries is None:
        exclude_countries = ["CN", "HK"]

    keywords = load_keywords()
    seen_brands = load_seen_leads()
    print(f"Loaded {len(keywords)} keywords to hunt. Historical deduplication database: {len(seen_brands)} brands.")

    extractor = AmazonExtractor(marketplace=marketplace, delay_between_requests=delay)
    new_discovered_leads = []

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
                progress_callback=lambda u: print(f"  -> {u.get('message', '')}") if "Verified PL" in u.get('message', '') or "Disqualified" in u.get('message', '') else None
            )

            for r in results:
                b_norm = (r.get("brand_name") or "").lower().strip()
                if b_norm and b_norm not in seen_brands:
                    seen_brands.add(b_norm)
                    new_discovered_leads.append(r)
                    print(f"  ⭐ NEW LEAD SECURED: '{r.get('brand_name')}' | Reviews: {r.get('reviews')} | Seller: {r.get('seller_country')} | Contact Email: {r.get('email')} | Phone: {r.get('phone')}")

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
                ok, msg = send_leads_email(new_discovered_leads, config=cfg)
                if ok:
                    print(f"✅ {msg}")
                else:
                    print(f"❌ Email sending failed: {msg}")
            else:
                print("ℹ️ Email dispatch skipped: Email credentials not configured yet.")
                print("   Set SENDER_EMAIL, SENDER_PASSWORD, and RECEIVER_EMAIL in your environment or email_config.json.")
    else:
        print("No new leads discovered in this cycle (all matching brands were already in historical leads).")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automated Amazon Private Label Hunter")
    parser.add_argument("--pages", type=int, default=2, help="Max search pages per keyword (default 2)")
    parser.add_argument("--marketplace", type=str, default="amazon.com", help="Amazon marketplace domain")
    parser.add_argument("--no-email", action="store_true", help="Skip sending email report")
    args = parser.parse_args()

    run_auto_hunt(
        max_pages_per_kw=args.pages,
        marketplace=args.marketplace,
        send_email=not args.no_email
    )
