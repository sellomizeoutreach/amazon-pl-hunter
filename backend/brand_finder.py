import re
import time
import urllib.parse
from typing import Dict, Any, Optional, List, Set
from bs4 import BeautifulSoup
import requests
from ddgs import DDGS

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
    
    # Filter out excluded generic/aggregator platforms
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

def clean_phone(phone_str: str) -> Optional[str]:
    """Validate and clean a phone number string."""
    if not phone_str:
        return None
    p = phone_str.strip()
    digits = re.sub(r'[^\d]', '', p)
    if not (10 <= len(digits) <= 15):
        return None
    # Reject strings with repetitive digits or trivial sequences
    if len(set(digits)) <= 2:
        return None
    # Avoid dates like 2026100612
    if digits.startswith(('19', '20')) and len(digits) == 10 and digits[4:6] in ['01','02','03','04','05','06','07','08','09','10','11','12']:
        return None
    return p

def extract_contacts_from_soup(soup: BeautifulSoup, base_url: str = "") -> Dict[str, Any]:
    """Extract mailto links, tel links, and regex emails/phones from page soup."""
    emails: Set[str] = set()
    phones: Set[str] = set()
    
    # 1. Direct mailto links
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

    # 3. Contextual phone number search in text
    for tag in soup.find_all(['p', 'span', 'li', 'div', 'footer']):
        tag_text = tag.get_text(separator=' ').strip()
        if any(kw in tag_text.lower() for kw in ['phone', 'tel', 'call', 'contact', 'hotline', 'toll free', 'support', 'customer service']):
            for match in PHONE_PATTERN.finditer(tag_text):
                matched_str = match.group(0).strip()
                valid_tel = clean_phone(matched_str)
                if valid_tel:
                    phones.add(valid_tel)
                    
    return {
        "emails": list(emails),
        "phones": list(phones)
    }

def find_brand_website_and_contacts(brand_name: str, delay_seconds: float = 0.1) -> Dict[str, Any]:
    """
    Discovers:
    1. Official brand website
    2. Public email address on the website
    3. Phone number from the website (if available)
    """
    if not brand_name or not brand_name.strip():
        return {
            "website": "Not Found",
            "email": "Not Found",
            "phone": "Not Found",
            "contact_status": "Not Found"
        }

    brand_clean = brand_name.strip()
    cache_key = brand_clean.lower()
    if cache_key in BRAND_CONTACT_CACHE:
        return BRAND_CONTACT_CACHE[cache_key]

    brand_tokens = [t.lower() for t in re.findall(r'[a-zA-Z0-9]+', brand_clean) if len(t) > 2]
    compact_brand = re.sub(r'[^a-z0-9]', '', brand_clean.lower())

    website_url = ""
    discovered_emails: List[str] = []
    discovered_phones: List[str] = []

    ddgs = DDGS(timeout=4)

    # Step 1: Search for official brand website
    try:
        time.sleep(delay_seconds)
        search_query = f"{brand_clean} official website"
        results = list(ddgs.text(search_query, max_results=5))

        for item in results:
            href = item.get('href', '')
            parsed = urllib.parse.urlparse(href)
            netloc = parsed.netloc.lower()
            if is_valid_brand_domain(netloc, brand_tokens):
                # Check if domain resembles the brand or title contains official brand name
                compact_netloc = re.sub(r'[^a-z0-9]', '', netloc)
                if compact_brand in compact_netloc or any(t in netloc for t in brand_tokens) or not website_url:
                    website_url = f"{parsed.scheme}://{parsed.netloc}"
                    break
    except Exception:
        pass

    # Step 2: If website found, crawl homepage and contact page for emails & phone numbers
    if website_url:
        try:
            resp = requests.get(website_url, headers=REQUEST_HEADERS, timeout=4)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                contacts = extract_contacts_from_soup(soup, website_url)
                discovered_emails.extend(contacts["emails"])
                discovered_phones.extend(contacts["phones"])

                # If missing either email or phone, check contact / about / support page
                if not discovered_emails or not discovered_phones:
                    contact_links = []
                    for a in soup.find_all('a', href=True):
                        href = a['href']
                        if any(kw in href.lower() for kw in ['contact', 'about', 'support', 'help', 'service']):
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
                                if discovered_emails and discovered_phones:
                                    break
                        except Exception:
                            continue
        except Exception:
            pass

    # Step 3: Fallback Natural Search for Public Contact Information if missing
    if not discovered_emails or not discovered_phones:
        try:
            time.sleep(delay_seconds)
            fallback_query = f"{brand_clean} contact email phone customer service"
            fb_results = list(ddgs.text(fallback_query, max_results=3))
            for item in fb_results:
                snippet = f"{item.get('title', '')} {item.get('body', '')}"
                
                # Check for email in snippet
                if not discovered_emails:
                    snippet_emails = EMAIL_REGEX.findall(snippet)
                    for em in snippet_emails:
                        valid_em = clean_email(em)
                        if valid_em:
                            discovered_emails.append(valid_em)

                # Check for phone in snippet
                if not discovered_phones:
                    for match in PHONE_PATTERN.finditer(snippet):
                        valid_tel = clean_phone(match.group(0))
                        if valid_tel:
                            discovered_phones.append(valid_tel)

                # Fallback website if still not found
                if not website_url:
                    parsed = urllib.parse.urlparse(item.get('href', ''))
                    if is_valid_brand_domain(parsed.netloc, brand_tokens):
                        website_url = f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            pass

    # Select best email
    selected_email = "Not Found"
    if discovered_emails:
        # Prioritize domain-matching email or support/info email
        unique_emails = list(dict.fromkeys(discovered_emails))
        netloc_part = urllib.parse.urlparse(website_url).netloc.replace('www.', '') if website_url else ""
        priority_emails = [e for e in unique_emails if (netloc_part and netloc_part in e) or any(e.startswith(p) for p in ['support@', 'info@', 'contact@', 'service@', 'hello@', 'sales@'])]
        selected_email = priority_emails[0] if priority_emails else unique_emails[0]

    # Select best phone number
    selected_phone = "Not Found"
    if discovered_phones:
        unique_phones = list(dict.fromkeys(discovered_phones))
        # Filter for cleanest formatted phone
        selected_phone = unique_phones[0]

    result = {
        "website": website_url or "Not Found",
        "email": selected_email,
        "phone": selected_phone,
        "contact_status": "Found" if (website_url or selected_email != "Not Found" or selected_phone != "Not Found") else "Not Found"
    }

    BRAND_CONTACT_CACHE[cache_key] = result
    return result
