"""
Brand Contact & Direct Decision Maker Finder
--------------------------------------------
Finds official brand website and contact channels:
- Distinguishes between Customer Service emails (support@, info@) and Direct Personal emails (founder/exec)
- Extracts direct phone numbers and toll-free / support lines
- Discovers social media handles (Instagram, Twitter/X, Facebook, LinkedIn)
- Deep search for founder personal email and direct communication lines
- Classifies Contact Quality (⭐ Direct Decision Maker, 📧 General/Support Only, ❌ Uncontactable)
"""

import re
import time
import urllib.parse
from typing import Dict, Any, Optional, List, Set, Tuple
from bs4 import BeautifulSoup
import requests

try:
    from ddgs import DDGS
except Exception:
    try:
        from duckduckgo_search import DDGS
    except Exception:
        DDGS = None

# Cache to avoid repeated website/contact discovery for the same brand
BRAND_CONTACT_CACHE: Dict[str, Dict[str, Any]] = {}

# Domains that are definitely NOT brand websites
EXCLUDED_DOMAINS = {
    'amazon.', 'walmart.com', 'ebay.com', 'target.com', 'aliexpress.com', 'alibaba.com',
    'etsy.com', 'bestbuy.com', 'facebook.com', 'instagram.com', 'twitter.com', 'x.com',
    'linkedin.com', 'tiktok.com', 'pinterest.com', 'youtube.com', 'wikipedia.org',
    'reddit.com', 'quora.com', 'bloomberg.com', 'crunchbase.com', 'pitchbook.com',
    'glassdoor.com', 'zoominfo.com', 'yelp.com', 'trustpilot.com', 'indeed.com',
    'bbb.org', 'google.com', 'bing.com', 'yahoo.com', 'duckduckgo.com',
    'medium.com', 'apple.com', 'play.google.com', 'prnewswire.com', 'businesswire.com',
    'shopify.com', 'wix.com', 'wordpress.com', 'squarespace.com'
}

INVALID_EMAIL_DOMAINS = {
    'example.com', 'domain.com', 'yourdomain.com', 'email.com', 'sentry.io',
    'wixpress.com', 'shopify.com', 'schema.org', 'w3.org', 'cloudflare.com',
    'github.com', 'gravatar.com', 'wordpress.org', 'googleapis.com'
}

INVALID_EMAIL_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp', '.ico', '.css', '.js')

EMAIL_REGEX = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')

# International / US phone patterns
PHONE_PATTERN = re.compile(
    r'(?:(?:\+?1\s*(?:[.-]\s*)?)?(?:\(\s*([2-9]\d{2})\s*\)|([2-9]\d{2}))\s*(?:[.-]\s*)?([2-9]\d{2})\s*(?:[.-]\s*)?(\d{4})'
    r'|'
    r'\+?[1-9]\d{0,2}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{2,4}[-.\s]?\d{3,4})'
)

# Common generic customer service prefixes
GENERIC_EMAIL_PREFIXES = {
    'support', 'info', 'service', 'services', 'contact', 'customercare', 'customerservice',
    'help', 'sales', 'hello', 'hi', 'press', 'media', 'team', 'office', 'admin',
    'inquiries', 'inquiry', 'billing', 'orders', 'order', 'feedback', 'returns',
    'care', 'general', 'shop', 'store', 'mail', 'compliance', 'privacy', 'legal'
}

REQUEST_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}

def is_valid_brand_domain(netloc: str, brand_tokens: List[str]) -> bool:
    """Check if domain is plausible for the brand and not a directory/marketplace."""
    if not netloc:
        return False
    netloc_clean = netloc.lower().strip()
    if any(ex in netloc_clean for ex in EXCLUDED_DOMAINS):
        return False
    return True

def clean_email(email_str: str) -> Optional[str]:
    """Validate and clean email address."""
    if not email_str:
        return None
    em = email_str.strip().rstrip('.').rstrip(',').lower()
    if em.endswith(INVALID_EMAIL_EXTENSIONS):
        return None
    if any(em.endswith(f"@{inv}") or f"@{inv}" in em for inv in INVALID_EMAIL_DOMAINS):
        return None
    if len(em) < 6 or len(em) > 60 or '@' not in em:
        return None
    parts = em.split('@')
    if len(parts) != 2 or '.' not in parts[1]:
        return None
    if parts[0] in ['username', 'name', 'user', 'test', 'yourname', 'email']:
        return None
    return em

def is_generic_email(email: str) -> bool:
    """Determines if an email address is generic customer service vs personal."""
    if not email or '@' not in email:
        return True
    prefix = email.split('@')[0].lower()
    clean_prefix = re.sub(r'[^a-z]', '', prefix)
    if clean_prefix in GENERIC_EMAIL_PREFIXES:
        return True
    for g in GENERIC_EMAIL_PREFIXES:
        if clean_prefix.startswith(g):
            return True
    return False

def is_personal_email_match(email: str, founder_name: str = "") -> bool:
    """Checks if an email appears to belong to a specific person or founder."""
    if not email or is_generic_email(email):
        return False
    prefix = email.split('@')[0].lower()
    if founder_name and founder_name != "Not Found":
        names = [n.lower() for n in re.findall(r'[a-zA-Z]+', founder_name) if len(n) > 2]
        if any(n in prefix for n in names):
            return True
    # If it contains standard personal naming convention (first.last, first_last, or standalone name)
    if re.match(r'^[a-z]{2,20}[\._\-][a-z]{2,20}$', prefix):
        return True
    return not is_generic_email(email)

def clean_phone(phone_str: str) -> Optional[str]:
    """Validate and clean a phone number string."""
    if not phone_str:
        return None
    p = phone_str.strip()
    digits = re.sub(r'[^\d]', '', p)
    if not (10 <= len(digits) <= 15):
        return None
    if len(set(digits)) <= 2:
        return None
    if digits.startswith(('19', '20')) and len(digits) == 10 and digits[4:6] in ['01','02','03','04','05','06','07','08','09','10','11','12']:
        return None
    return p

def extract_social_links(soup: BeautifulSoup) -> Dict[str, str]:
    """Extracts social media profile links from brand page."""
    socials = {
        "instagram": "",
        "twitter": "",
        "facebook": "",
        "linkedin_company": ""
    }
    if not soup:
        return socials

    for a in soup.find_all('a', href=True):
        href = a['href'].strip()
        href_lower = href.lower()

        if ('instagram.com/' in href_lower or 'instagr.am/' in href_lower) and not socials["instagram"]:
            if not any(ign in href_lower for ign in ['/p/', '/reel/', '/share', '/explore']):
                socials["instagram"] = href
        elif ('twitter.com/' in href_lower or 'x.com/' in href_lower) and not socials["twitter"]:
            if not any(ign in href_lower for ign in ['/status/', '/intent/', '/share']):
                socials["twitter"] = href
        elif 'facebook.com/' in href_lower and not socials["facebook"]:
            if not any(ign in href_lower for ign in ['/sharer', '/share', '/plugins']):
                socials["facebook"] = href
        elif 'linkedin.com/company/' in href_lower and not socials["linkedin_company"]:
            socials["linkedin_company"] = href

    return socials

def extract_contacts_from_soup(soup: BeautifulSoup, base_url: str = "") -> Dict[str, Any]:
    """Extract mailto links, tel links, social links, and text emails/phones."""
    emails: Set[str] = set()
    phones: Set[str] = set()
    
    # 1. Direct mailto links & tel links
    for a in soup.find_all('a', href=True):
        href = a['href'].strip()
        if href.startswith('mailto:'):
            raw_em = href.replace('mailto:', '').split('?')[0].strip()
            valid_em = clean_email(raw_em)
            if valid_em:
                emails.add(valid_em)
        elif href.startswith('tel:'):
            raw_tel = href.replace('tel:', '').strip()
            valid_tel = clean_phone(raw_tel)
            if valid_tel:
                phones.add(valid_tel)

    # 2. Text-level email search
    text_sample = soup.get_text(separator=' ')
    found_emails = EMAIL_REGEX.findall(text_sample)
    for em in found_emails:
        valid_em = clean_email(em)
        if valid_em:
            emails.add(valid_em)

    # 3. Contextual phone number search
    for tag in soup.find_all(['p', 'span', 'li', 'div', 'footer']):
        tag_text = tag.get_text(separator=' ').strip()
        if any(kw in tag_text.lower() for kw in ['phone', 'tel', 'call', 'contact', 'hotline', 'toll free', 'support', 'customer service']):
            for match in PHONE_PATTERN.finditer(tag_text):
                matched_str = match.group(0).strip()
                valid_tel = clean_phone(matched_str)
                if valid_tel:
                    phones.add(valid_tel)

    socials = extract_social_links(soup)

    return {
        "emails": list(emails),
        "phones": list(phones),
        "socials": socials
    }

def deep_search_founder_personal_contact(
    founder_name: str,
    brand_name: str,
    website_domain: str = ""
) -> Dict[str, Any]:
    """
    Searches for founder's direct personal email or contact route when founder is known.
    """
    if not DDGS or not founder_name or founder_name in ["Not Found", ""]:
        return {"personal_email": None, "direct_phone": None}

    queries = []
    if website_domain:
        queries.append(f'"{founder_name}" "{website_domain}" email')
    queries.append(f'"{founder_name}" "{brand_name}" email OR contact OR "@"')

    ddgs = DDGS(timeout=4)
    for q in queries:
        try:
            time.sleep(0.15)
            results = list(ddgs.text(q, max_results=3))
            for item in results:
                body = f"{item.get('title', '')} {item.get('body', '')}"
                # Search for personal emails in snippet
                em_matches = EMAIL_REGEX.findall(body)
                for raw_em in em_matches:
                    v_em = clean_email(raw_em)
                    if v_em and is_personal_email_match(v_em, founder_name):
                        return {"personal_email": v_em, "direct_phone": None}

                # Search for direct phone
                for p_match in PHONE_PATTERN.finditer(body):
                    v_ph = clean_phone(p_match.group(0))
                    if v_ph:
                        return {"personal_email": None, "direct_phone": v_ph}
        except Exception:
            continue

    return {"personal_email": None, "direct_phone": None}

def find_brand_website_and_contacts(
    brand_name: str,
    founder_name: str = "",
    delay_seconds: float = 0.1
) -> Dict[str, Any]:
    """
    Discovers:
    1. Official brand website
    2. Separates Customer Service Email vs Direct Personal Email
    3. Direct Phone Number & CS Phone
    4. Social profiles (Instagram, Twitter, Facebook, LinkedIn Company)
    5. Computes Contact Quality Rating
    """
    if not brand_name or not brand_name.strip():
        return {
            "website": "Not Found",
            "email": "Not Found",
            "personal_email": "Not Found",
            "cs_email": "Not Found",
            "email_type": "None",
            "phone": "Not Found",
            "social_profiles": {},
            "social_summary": "Not Found",
            "contact_quality": "❌ Uncontactable",
            "contact_status": "Not Found"
        }

    brand_clean = brand_name.strip()
    cache_key = f"{brand_clean.lower()}:{founder_name.lower()}"
    if cache_key in BRAND_CONTACT_CACHE:
        return BRAND_CONTACT_CACHE[cache_key]

    brand_tokens = [t.lower() for t in re.findall(r'[a-zA-Z0-9]+', brand_clean) if len(t) > 2]
    compact_brand = re.sub(r'[^a-z0-9]', '', brand_clean.lower())

    website_url = ""
    discovered_emails: List[str] = []
    discovered_phones: List[str] = []
    social_profiles: Dict[str, str] = {
        "instagram": "",
        "twitter": "",
        "facebook": "",
        "linkedin_company": ""
    }

    ddgs = DDGS(timeout=4) if DDGS else None

    # Step 1: Search for official brand website
    if ddgs:
        try:
            time.sleep(delay_seconds)
            search_query = f"{brand_clean} official website"
            results = list(ddgs.text(search_query, max_results=5))

            for item in results:
                href = item.get('href', '')
                parsed = urllib.parse.urlparse(href)
                netloc = parsed.netloc.lower()
                if is_valid_brand_domain(netloc, brand_tokens):
                    compact_netloc = re.sub(r'[^a-z0-9]', '', netloc)
                    if compact_brand in compact_netloc or any(t in netloc for t in brand_tokens) or not website_url:
                        website_url = f"{parsed.scheme}://{parsed.netloc}"
                        break
        except Exception:
            pass

    # Step 2: Crawl brand website homepage and contact pages
    if website_url:
        try:
            resp = requests.get(website_url, headers=REQUEST_HEADERS, timeout=4)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                contacts = extract_contacts_from_soup(soup, website_url)
                discovered_emails.extend(contacts["emails"])
                discovered_phones.extend(contacts["phones"])
                for k, v in contacts["socials"].items():
                    if v and not social_profiles[k]:
                        social_profiles[k] = v

                # Check contact / about / support page if needed
                if not discovered_emails or not discovered_phones:
                    contact_links = []
                    for a in soup.find_all('a', href=True):
                        href = a['href']
                        if any(kw in href.lower() for kw in ['contact', 'about', 'support', 'help', 'service', 'team']):
                            full_url = urllib.parse.urljoin(website_url, href)
                            if full_url != website_url and full_url not in contact_links and not full_url.startswith('mailto:'):
                                contact_links.append(full_url)
                    
                    for c_url in contact_links[:2]:
                        try:
                            c_resp = requests.get(c_url, headers=REQUEST_HEADERS, timeout=4)
                            if c_resp.status_code == 200:
                                c_soup = BeautifulSoup(c_resp.text, 'html.parser')
                                c_contacts = extract_contacts_from_soup(c_soup, c_url)
                                discovered_emails.extend(c_contacts["emails"])
                                discovered_phones.extend(c_contacts["phones"])
                                for k, v in c_contacts["socials"].items():
                                    if v and not social_profiles[k]:
                                        social_profiles[k] = v
                                if discovered_emails and discovered_phones:
                                    break
                        except Exception:
                            continue
        except Exception:
            pass

    # Step 3: Natural fallback search if contacts still missing
    if ddgs and (not discovered_emails or not discovered_phones):
        try:
            time.sleep(delay_seconds)
            fb_query = f"{brand_clean} contact email phone customer service"
            fb_results = list(ddgs.text(fb_query, max_results=3))
            for item in fb_results:
                snippet = f"{item.get('title', '')} {item.get('body', '')}"
                if not discovered_emails:
                    for em in EMAIL_REGEX.findall(snippet):
                        v_em = clean_email(em)
                        if v_em:
                            discovered_emails.append(v_em)
                if not discovered_phones:
                    for match in PHONE_PATTERN.finditer(snippet):
                        v_ph = clean_phone(match.group(0))
                        if v_ph:
                            discovered_phones.append(v_ph)
                if not website_url:
                    parsed = urllib.parse.urlparse(item.get('href', ''))
                    if is_valid_brand_domain(parsed.netloc, brand_tokens):
                        website_url = f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            pass

    # Step 4: Deep search for Founder's direct personal email if founder is known
    personal_email = None
    direct_phone = None
    if founder_name and founder_name != "Not Found":
        web_domain = urllib.parse.urlparse(website_url).netloc.replace('www.', '') if website_url else ""
        founder_contacts = deep_search_founder_personal_contact(founder_name, brand_clean, web_domain)
        personal_email = founder_contacts.get("personal_email")
        direct_phone = founder_contacts.get("direct_phone")

    # Step 5: Separate personal vs CS emails
    unique_emails = list(dict.fromkeys(discovered_emails))
    personal_candidates = [e for e in unique_emails if not is_generic_email(e)]
    cs_candidates = [e for e in unique_emails if is_generic_email(e)]

    if not personal_email and personal_candidates:
        # Check if any candidate matches founder name
        matching = [e for e in personal_candidates if is_personal_email_match(e, founder_name)]
        personal_email = matching[0] if matching else personal_candidates[0]

    cs_email = cs_candidates[0] if cs_candidates else None

    # Step 6: Determine Primary Outreach Email & Type
    # If personal email found, it takes highest priority!
    if personal_email:
        primary_email = personal_email
        email_type = "Direct Personal"
    elif cs_email:
        primary_email = cs_email
        email_type = "Customer Support"
    else:
        primary_email = "Not Found"
        email_type = "None"

    # Best phone number
    selected_phone = direct_phone or (discovered_phones[0] if discovered_phones else "Not Found")

    # Social summary
    social_items = [f"{k.capitalize()}: {v}" for k, v in social_profiles.items() if v]
    social_summary = " | ".join(social_items) if social_items else "Not Found"

    # Contact Quality Classification
    if personal_email or direct_phone:
        contact_quality = "⭐ Direct Decision Maker"
    elif primary_email != "Not Found" or selected_phone != "Not Found":
        contact_quality = "📧 General / Support Only"
    else:
        contact_quality = "❌ Uncontactable"

    result = {
        "website": website_url or "Not Found",
        "email": primary_email,
        "personal_email": personal_email or "Not Found",
        "cs_email": cs_email or "Not Found",
        "email_type": email_type,
        "phone": selected_phone,
        "social_profiles": social_profiles,
        "social_summary": social_summary,
        "contact_quality": contact_quality,
        "contact_status": "Found" if contact_quality != "❌ Uncontactable" else "Not Found"
    }

    BRAND_CONTACT_CACHE[cache_key] = result
    return result
