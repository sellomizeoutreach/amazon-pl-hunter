"""
Brand Health Auditor & Strategy Generator
------------------------------------------
Analyzes Amazon brand catalogs for:
1. ASIN Health & Critical Problem Detection:
   - Suppressed / Currently Unavailable listings
   - Suppressed Buy Box (no Add to Cart button / "Available from these sellers")
   - Amazon's Orange "Frequently Returned Item" badge
   - Negative reviews / critical rating (< 3.8 stars)
   - Missing A+ content, missing listing video, low bullet count
2. Brand Persona & Stage Segmentation:
   - 🚀 New Launch Brand: Launched within 12 months, in launch sprint with small team
   - 📉 Stagnant Veteran Brand: Launched 2+ years ago with low review velocity / unoptimized assets
   - ⚠️ Distressed Catalog: Active suppression, return badges, or rating crises
   - 🌱 Growing Challenger: Healthy velocity and positive trajectory
3. Tailored Growth Strategy & Turnaround Pitch:
   - Current baseline statistics
   - Projected achievable milestones (2x-3x velocity, rating recovery, Buy Box restoration)
   - Personalized cold outreach email hook ready for copy-pasting
"""

import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from bs4 import BeautifulSoup

MONTH_MAP = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4,
    'may': 5, 'june': 6, 'july': 7, 'august': 8,
    'september': 9, 'october': 10, 'november': 11, 'december': 12,
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'sept': 9, 'oct': 10, 'nov': 11, 'dec': 12
}

def parse_date_first_available(soup: BeautifulSoup) -> Tuple[str, Optional[int]]:
    """
    Extracts Date First Available from Amazon listing DOM and calculates age in months.
    Returns (date_str, age_months).
    """
    if not soup:
        return "Not Listed", None

    date_str = ""
    # 1. Detail Bullets wrapper (#detailBulletsWrapper_feature_div)
    bullets_div = soup.select_one('#detailBulletsWrapper_feature_div, #detailBullets_feature_div')
    if bullets_div:
        for li in bullets_div.select('li'):
            text = li.get_text(separator=' ')
            if 'date first available' in text.lower():
                m = re.search(r'date first available\s*[:\u200f\u200e]\s*([a-zA-Z0-9,\s]+)', text, re.I)
                if m:
                    date_str = m.group(1).strip()
                    break

    # 2. Product Details tabular section (#productDetails_db_sections)
    if not date_str:
        for tr in soup.select('table#productDetails_techSpec_section_1 tr, table#productDetails_db_sections tr, div.prodDetTable tr'):
            th = tr.select_one('th')
            td = tr.select_one('td')
            if th and td and 'date first available' in th.get_text().lower():
                date_str = td.get_text(strip=True)
                break

    # 3. Fallback text search across the page
    if not date_str:
        raw_text = soup.get_text(separator=' ')
        m = re.search(r'Date First Available\s*[:\u200f\u200e]\s*([A-Za-z]+ \d{1,2}, \d{4})', raw_text, re.I)
        if not m:
            m = re.search(r'Date First Available\s*[:\u200f\u200e]\s*(\d{1,2} [A-Za-z]+ \d{4})', raw_text, re.I)
        if m:
            date_str = m.group(1).strip()

    if not date_str:
        return "Not Listed", None

    # Clean date string
    date_clean = re.sub(r'[\u200f\u200e]', '', date_str).strip()

    # Parse age in months
    age_months = None
    try:
        dt = None
        # Try "Month DD, YYYY" (e.g. October 15, 2023)
        m_us = re.search(r'([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})', date_clean)
        if m_us:
            m_name, day, year = m_us.group(1).lower(), int(m_us.group(2)), int(m_us.group(3))
            m_num = MONTH_MAP.get(m_name)
            if m_num:
                dt = datetime(year, m_num, min(day, 28))

        # Try "DD Month YYYY" (e.g. 15 October 2023)
        if not dt:
            m_eu = re.search(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})', date_clean)
            if m_eu:
                day, m_name, year = int(m_eu.group(1)), m_eu.group(2).lower(), int(m_eu.group(3))
                m_num = MONTH_MAP.get(m_name)
                if m_num:
                    dt = datetime(year, m_num, min(day, 28))

        if dt:
            now = datetime.now()
            diff_days = (now - dt).days
            age_months = max(1, int(diff_days / 30.4))
    except Exception:
        pass

    return date_clean, age_months

def extract_bsr(soup: BeautifulSoup) -> str:
    """Extract Best Sellers Rank from listing page."""
    if not soup:
        return "Not Ranked"

    # 1. Detail Bullets
    bullets = soup.select_one('#detailBulletsWrapper_feature_div, #detailBullets_feature_div')
    if bullets:
        for li in bullets.select('li'):
            text = li.get_text(separator=' ')
            if 'best sellers rank' in text.lower():
                m = re.search(r'#([0-9,]+)\s+in\s+([A-Za-z\s&,]+)', text)
                if m:
                    return f"#{m.group(1)} in {m.group(2).split('(')[0].strip()}"

    # 2. Tech spec tables
    for tr in soup.select('table#productDetails_techSpec_section_1 tr, table#productDetails_db_sections tr'):
        th = tr.select_one('th')
        td = tr.select_one('td')
        if th and td and 'best sellers rank' in th.get_text().lower():
            text = td.get_text(separator=' ')
            m = re.search(r'#([0-9,]+)\s+in\s+([A-Za-z\s&,]+)', text)
            if m:
                return f"#{m.group(1)} in {m.group(2).split('(')[0].strip()}"

    return "Not Ranked"

def audit_asin_health(soup: BeautifulSoup, asin: str) -> Dict[str, Any]:
    """
    Evaluates listing health, suppression, Buy Box status, and problem badges for an ASIN.
    """
    if not soup:
        return {
            "asin": asin,
            "is_suppressed": False,
            "is_buybox_suppressed": False,
            "has_frequently_returned_badge": False,
            "rating": 0.0,
            "reviews": 0,
            "bsr": "Not Ranked",
            "date_first_available": "Not Listed",
            "age_months": None,
            "has_aplus": False,
            "has_video": False,
            "bullet_count": 0,
            "health_issues": []
        }

    issues = []

    # 1. Date First Available & Listing Age
    date_str, age_months = parse_date_first_available(soup)

    # 2. Suppressed / Currently Unavailable / Out of Stock
    is_suppressed = False
    avail_el = soup.select_one('#availability, #availabilityInsideBuyBox_feature_div, #outOfStock')
    if avail_el:
        avail_text = avail_el.get_text(separator=' ').strip().lower()
        if any(w in avail_text for w in ['currently unavailable', "we don't know when or if this item will be back in stock", 'temporarily out of stock']):
            is_suppressed = True
            issues.append("🛑 Listing Suppressed / Currently Unavailable")

    # 3. Buy Box Suppression (Missing 'Add to Cart' or 'Available from these sellers')
    is_buybox_suppressed = False
    add_to_cart = soup.select_one('#add-to-cart-button, #buy-now-button, input#add-to-cart-button')
    see_all_buying = soup.select_one('#buybox-see-all-buying-choices, #all-offers-display, #dynamic-aod-ingress-box')
    
    if not is_suppressed:
        if not add_to_cart:
            is_buybox_suppressed = True
            issues.append("⚠️ Buy Box Suppressed (No Add-to-Cart Button)")
        elif see_all_buying and 'available from these sellers' in see_all_buying.get_text().lower():
            is_buybox_suppressed = True
            issues.append("⚠️ Buy Box Hijacked or Suppressed ('Available from these sellers')")

    # 4. Amazon's Orange "Frequently Returned Item" Badge
    has_frequently_returned_badge = False
    ret_el = soup.select_one('.frequently-returned-item, [data-csa-c-element-id*="frequently-returned"], .frequently-returned-badge')
    if ret_el:
        has_frequently_returned_badge = True
        issues.append("🔥 Orange 'Frequently Returned Item' Badge Active")
    else:
        # Check text in body
        text_lower = soup.get_text(separator=' ').lower()
        if 'frequently returned item' in text_lower or 'customers usually keep this item' in text_lower:
            has_frequently_returned_badge = True
            issues.append("🔥 Orange 'Frequently Returned Item' Badge Active")

    # 5. Rating & Reviews
    rating = 0.0
    r_node = soup.select_one('#acrPopover, [data-hook="rating-out-of-text"], span.a-icon-alt')
    if r_node:
        m_r = re.search(r'([0-9\.]+)\s+out of\s+5', r_node.get_text())
        if m_r:
            try:
                rating = float(m_r.group(1))
            except Exception:
                pass

    reviews = 0
    rev_node = soup.select_one('#acrCustomerReviewText, [data-hook="total-review-count"]')
    if rev_node:
        rev_txt = rev_node.get_text(strip=True).replace(',', '')
        m_rev = re.search(r'(\d+)', rev_txt)
        if m_rev:
            try:
                reviews = int(m_rev.group(1))
            except Exception:
                pass

    if rating > 0 and rating < 3.8:
        issues.append(f"⭐ Critical Low Rating ({rating}★ < 3.8 Threshold)")

    # 6. A+ Content & Video Check
    has_aplus = bool(soup.select_one('#aplus, .aplus-v2, #dpx-aplus-brand-story_feature_div, [data-feature-name="aplus"]'))
    if not has_aplus:
        issues.append("🎨 Missing A+ Enhanced Brand Content")

    has_video = bool(soup.select_one('#vse-related-videos, .vse-video-wrapper, [data-video-url]'))
    if not has_video:
        issues.append("🎬 Missing Product Video in Main Gallery")

    # 7. Bullet Points
    bullets = soup.select('#feature-bullets ul li:not(.aok-hidden)')
    bullet_count = len(bullets)
    if bullet_count < 4:
        issues.append(f"📝 Suboptimal Copy ({bullet_count} bullets, recommended 5)")

    # 8. BSR
    bsr = extract_bsr(soup)

    return {
        "asin": asin,
        "is_suppressed": is_suppressed,
        "is_buybox_suppressed": is_buybox_suppressed,
        "has_frequently_returned_badge": has_frequently_returned_badge,
        "rating": rating,
        "reviews": reviews,
        "bsr": bsr,
        "date_first_available": date_str,
        "age_months": age_months,
        "has_aplus": has_aplus,
        "has_video": has_video,
        "bullet_count": bullet_count,
        "health_issues": issues
    }

def classify_brand_persona(
    age_months: Optional[int],
    reviews: int,
    catalog_health_issues: List[str],
    has_aplus: bool
) -> Tuple[str, str]:
    """
    Classifies the brand into a strategic outreach persona:
    - 🚀 New Launch Brand
    - 📉 Stagnant Veteran Brand
    - ⚠️ Distressed Catalog
    - 🌱 Growing Challenger
    Returns (persona_title, persona_badge).
    """
    has_distress = any(
        ('frequently returned' in iss.lower()) or 
        ('suppressed' in iss.lower()) or 
        ('critical low rating' in iss.lower())
        for iss in catalog_health_issues
    )

    if has_distress:
        return (
            "⚠️ Distressed Catalog (Active Issues)",
            "⚠️ Distressed"
        )

    # 🚀 New Launch: Launched within 12 months, or low reviews and launched within 18 months
    if age_months is not None and age_months <= 12:
        return (
            "🚀 New Launch Brand (Launching Phase / High Workload)",
            "🚀 New Launch"
        )
    if age_months is not None and age_months <= 18 and reviews < 50:
        return (
            "🚀 New Launch Brand (Early Launch Phase)",
            "🚀 New Launch"
        )

    # 📉 Stagnant Veteran: Live for 2+ years (24+ months) with low review count or lacking growth
    if age_months is not None and age_months >= 24 and reviews < 200:
        return (
            "📉 Stagnant Veteran Brand (2+ Yrs Live, Growth Lagging)",
            "📉 Stagnant Veteran"
        )
    if age_months is not None and age_months >= 36 and reviews < 350:
        return (
            "📉 Stagnant Veteran Brand (Established, Stagnant Velocity)",
            "📉 Stagnant Veteran"
        )

    # If age unknown but very low reviews with missing A+
    if age_months is None and reviews < 40 and not has_aplus:
        return (
            "🚀 New Launch Brand (Probable Recent Launch)",
            "🚀 New Launch"
        )

    return (
        "🌱 Growing Challenger (Scaling PL Brand)",
        "🌱 Growing Challenger"
    )

def generate_growth_strategy_and_pitch(
    brand_name: str,
    persona_badge: str,
    primary_asin: str,
    reviews: int,
    rating: float,
    age_months: Optional[int],
    date_first_available: str,
    health_issues: List[str],
    has_aplus: bool,
    has_video: bool,
    founder_name: str = "there"
) -> Dict[str, Any]:
    """
    Generates tailored current stats, achievable targets, and a personalized outreach hook.
    """
    salutation = founder_name.split()[0] if founder_name and founder_name != "Not Found" else "there"

    # Baseline summary
    age_desc = f"{age_months} months active (Launched {date_first_available})" if age_months else f"Launch date: {date_first_available}"
    rating_desc = f"{rating}★" if rating > 0 else "Unrated"
    issues_summary = "; ".join(health_issues) if health_issues else "No major listing blocks detected"

    current_stats = (
        f"Age: {age_desc} | Reviews: {reviews} | Rating: {rating_desc} | "
        f"A+ Content: {'Yes' if has_aplus else 'Missing'} | Issues: {issues_summary}"
    )

    # Projected achievable milestones
    if "Distressed" in persona_badge:
        achievable_milestones = (
            "1. Remove 'Frequently Returned' badge & restore Buy Box in 14-21 days\n"
            "2. Elevate star rating to 4.3★+ via packaging inserts & negative review mitigation\n"
            "3. Recover estimated 35-50% lost conversions from suppressed traffic"
        )
        pitch_hook = (
            f"Hey {salutation}, noticed Amazon recently flagged {brand_name}'s listing (ASIN {primary_asin}) "
            f"with listing suppression/return issues ({issues_summary}). We specialize in emergency listing turnaround "
            f"and return rate fixes to recover your Buy Box and protect your seller rank before Q4 volume."
        )

    elif "New Launch" in persona_badge:
        achievable_milestones = (
            "1. Scale from {reviews} to 150+ verified Vine & organic reviews in 60-90 days\n"
            "2. Launch high-converting A+ Brand Story & main image video (+28% conversion lift)\n"
            "3. Optimize exact-match PPC campaigns to rank top 15 organically for primary keywords"
        ).format(reviews=reviews)
        pitch_hook = (
            f"Hey {salutation}, congrats on getting {brand_name} live on Amazon ({date_first_available})! "
            f"Notice you have {reviews} reviews on ASIN {primary_asin}. Launch teams are usually stretched thin "
            f"between supply chain and PPC, so we built a 90-day launch sprint to get you past 150 reviews "
            f"and 3x your organic sales velocity without blowing PPC spend."
        )

    elif "Stagnant Veteran" in persona_badge:
        achievable_milestones = (
            f"1. Complete listing revitalization: modernize A+ Premium and video assets\n"
            "2. Re-index unranked high-volume backend keywords to unlock dormant search traffic\n"
            "3. Ramp velocity to 250+ reviews and 2x monthly revenue run-rate within 120 days"
        )
        pitch_hook = (
            f"Hey {salutation}, saw that {brand_name} has been active on Amazon since {date_first_available}, "
            f"yet your main catalog is sitting at {reviews} reviews with unoptimized creative assets. "
            f"Brands in your category with modern A+ Story & video are capturing 4x the market share—"
            f"we'd love to share our catalog turnaround playbook to re-energize your brand's growth."
        )

    else:
        achievable_milestones = (
            "1. Expand keyword footprint into high-intent long-tail search terms\n"
            "2. Increase average order value through brand bundle virtual cross-promotions\n"
            "3. Scale to category top-100 BSR with automated review acquisition"
        )
        pitch_hook = (
            f"Hey {salutation}, came across {brand_name} while analyzing high-potential brands on Amazon. "
            f"Your product (ASIN {primary_asin}) has solid fundamentals ({reviews} reviews). "
            f"We put together a custom growth audit showing 3 key keyword gaps your competitors are winning on."
        )

    return {
        "current_stats": current_stats,
        "achievable_milestones": achievable_milestones,
        "pitch_hook": pitch_hook
    }
