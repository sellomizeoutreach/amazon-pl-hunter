import re
import urllib.parse
from typing import Dict, Any, Optional
from bs4 import BeautifulSoup
from curl_cffi import requests

# Cache to prevent repeated network requests for the same seller
SELLER_INFO_CACHE: Dict[str, Dict[str, Any]] = {}

COUNTRY_NAMES = {
    "US": "United States",
    "CN": "China",
    "HK": "Hong Kong",
    "GB": "United Kingdom",
    "UK": "United Kingdom",
    "DE": "Germany",
    "CA": "Canada",
    "FR": "France",
    "IT": "Italy",
    "ES": "Spain",
    "IN": "India",
    "JP": "Japan",
    "AU": "Australia",
    "MX": "Mexico",
    "NL": "Netherlands",
    "PL": "Poland",
    "SE": "Sweden",
    "SG": "Singapore",
    "TR": "Turkey",
    "AE": "UAE",
    "VN": "Vietnam",
    "TW": "Taiwan",
    "KR": "South Korea",
}

COUNTRY_FLAGS = {
    "US": "US",
    "CN": "CN",
    "HK": "HK",
    "GB": "GB",
    "UK": "UK",
    "DE": "DE",
    "CA": "CA",
    "FR": "FR",
    "IT": "IT",
    "ES": "ES",
    "IN": "IN",
    "JP": "JP",
    "AU": "AU",
    "MX": "MX",
    "NL": "NL",
    "VN": "VN",
    "TW": "TW",
    "KR": "KR",
}

def extract_seller_id_from_url_or_tag(href_or_tag: Any) -> Optional[str]:
    """Extract Amazon merchant / seller ID token (e.g. A15HNQ673UZUPL) from href string or Tag."""
    if not href_or_tag:
        return None
    href = href_or_tag.get('href', '') if hasattr(href_or_tag, 'get') else str(href_or_tag)
    if not href:
        return None
    m = re.search(r'[?&](?:seller|merchant)=([A-Z0-9]{10,25})', href)
    if m:
        return m.group(1)
    m2 = re.search(r'/(?:shops|sp|seller)/([A-Z0-9]{10,25})', href)
    if m2:
        return m2.group(1)
    return None

def fetch_seller_information(marketplace: str = "amazon.com", seller_id: str = "", cookies: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    Fetches Amazon's 'Detailed Seller Information' page (/sp?seller=SELLER_ID):
    Extracts:
    1. Business Name (Legal entity name)
    2. Business Address (Registered physical address)
    3. Country / Region Code (e.g. US, CN, GB, DE, CA)
    """
    clean_marketplace = marketplace.replace('https://', '').replace('http://', '').strip('/')
    if not clean_marketplace.startswith('www.'):
        clean_marketplace = f"www.{clean_marketplace}"

    if not seller_id or len(seller_id) < 8:
        return {
            "seller_id": seller_id or "",
            "seller_business_name": "Not Available",
            "seller_address": "Not Available",
            "seller_country": "Unknown",
            "seller_country_name": "Unknown",
            "seller_country_display": "Unknown"
        }

    cache_key = f"{clean_marketplace}:{seller_id}"
    if cache_key in SELLER_INFO_CACHE:
        return SELLER_INFO_CACHE[cache_key]

    url = f"https://{clean_marketplace}/sp?seller={seller_id}"
    req_cookies = dict(cookies or {})
    req_cookies['i18n-prefs'] = 'USD'

    try:
        resp = requests.get(
            url,
            impersonate="chrome124",
            headers={"Accept-Language": "en-US,en;q=0.9"},
            cookies=req_cookies,
            timeout=8
        )

        if resp.status_code != 200:
            res = {
                "seller_id": seller_id,
                "seller_business_name": "Not Available",
                "seller_address": "Not Available",
                "seller_country": "Unknown",
                "seller_country_name": "Unknown",
                "seller_country_display": "Unknown"
            }
            SELLER_INFO_CACHE[cache_key] = res
            return res

        soup = BeautifulSoup(resp.text, 'html.parser')

        business_name = ""
        address_lines = []

        # 1. Parse structured rows in Detailed Seller Information card
        for row in soup.find_all(class_='a-row'):
            txt = row.get_text(separator=' ', strip=True)
            if 'business name:' in txt.lower():
                m_bn = re.search(r'business name:\s*(.*?)(?:business address|\Z)', txt, re.I)
                if m_bn:
                    cand = m_bn.group(1).strip()
                    if cand and len(cand) < 120:
                        business_name = cand
                        break

        for row in soup.find_all(class_='indent-left'):
            line = row.get_text(strip=True)
            if line:
                address_lines.append(line)

        # 2. Fallback text parsing if classes differ
        if not address_lines or not business_name:
            full_text = soup.get_text(separator='\n', strip=True)
            m_sec = re.search(
                r'Detailed Seller Information.*?Business Name:\s*([^\n]+).*?Business Address:\s*(.*?)(?:Shipping Policies|Other Policies|Feedback|Customer Service|\Z)',
                full_text,
                re.DOTALL | re.I
            )
            if m_sec:
                if not business_name and m_sec.group(1):
                    business_name = m_sec.group(1).strip()
                if not address_lines and m_sec.group(2):
                    raw_addr = m_sec.group(2).strip()
                    address_lines = [l.strip() for l in raw_addr.split('\n') if l.strip() and len(l.strip()) < 80]

        # Country extraction (almost always the last line in Amazon's address)
        raw_country = address_lines[-1].strip().upper() if address_lines else "Unknown"
        country_code = "Unknown"

        # Standardize country code
        if raw_country in ["US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"]:
            country_code = "US"
        elif raw_country in ["CN", "CHINA", "PEOPLE'S REPUBLIC OF CHINA", "PRC"]:
            country_code = "CN"
        elif raw_country in ["HK", "HONG KONG"]:
            country_code = "HK"
        elif raw_country in ["GB", "UK", "UNITED KINGDOM", "GREAT BRITAIN"]:
            country_code = "GB"
        elif raw_country in ["DE", "GERMANY", "DEUTSCHLAND"]:
            country_code = "DE"
        elif raw_country in ["CA", "CANADA"]:
            country_code = "CA"
        elif raw_country in ["FR", "FRANCE"]:
            country_code = "FR"
        elif raw_country in ["IT", "ITALY", "ITALIA"]:
            country_code = "IT"
        elif raw_country in ["ES", "SPAIN", "ESPANA"]:
            country_code = "ES"
        elif raw_country in ["IN", "INDIA"]:
            country_code = "IN"
        elif raw_country in ["JP", "JAPAN"]:
            country_code = "JP"
        elif raw_country in ["AU", "AUSTRALIA"]:
            country_code = "AU"
        elif len(raw_country) == 2 and raw_country.isalpha():
            country_code = raw_country
        else:
            country_code = raw_country if raw_country != "UNKNOWN" else "Unknown"

        country_name = COUNTRY_NAMES.get(country_code, country_code)
        display_flag = COUNTRY_FLAGS.get(country_code, country_code)
        display_str = f"{display_flag} ({country_name})" if country_name != "Unknown" else "Unknown"

        result = {
            "seller_id": seller_id,
            "seller_business_name": business_name or "Not Available",
            "seller_address": ", ".join(address_lines) if address_lines else "Not Available",
            "seller_country": country_code,
            "seller_country_name": country_name,
            "seller_country_display": display_str
        }

        SELLER_INFO_CACHE[cache_key] = result
        return result

    except Exception:
        fallback = {
            "seller_id": seller_id,
            "seller_business_name": "Not Available",
            "seller_address": "Not Available",
            "seller_country": "Unknown",
            "seller_country_name": "Unknown",
            "seller_country_display": "Unknown"
        }
        SELLER_INFO_CACHE[cache_key] = fallback
        return fallback

def matches_region_filter(seller_country: str, region_filter: Optional[str]) -> bool:
    """
    Checks if a seller's registered country matches the requested region filter:
    - 'ALL' or None: Matches everything
    - 'US': United States only
    - 'NON_CN': Non-China (all sellers NOT in CN/HK)
    - 'CN': China & Hong Kong (CN, HK)
    - 'UK_EU': United Kingdom & Europe (GB, UK, DE, FR, IT, ES, NL, PL, SE)
    - 'CA': Canada
    """
    if not region_filter or region_filter.upper() in ["ALL", "ANY", "ALL REGIONS", ""]:
        return True

    c = (seller_country or "UNKNOWN").upper().strip()
    r = region_filter.upper().strip()

    if r == "US":
        return c == "US"
    elif r in ["NON_CN", "NON-CHINA", "NON CHINA", "WESTERN"]:
        return c not in ["CN", "HK"] and c != "UNKNOWN"
    elif r in ["CN", "CHINA", "CN_HK"]:
        return c in ["CN", "HK"]
    elif r in ["UK_EU", "EU", "EUROPE"]:
        return c in ["GB", "UK", "DE", "FR", "IT", "ES", "NL", "PL", "SE", "IE"]
    elif r == "CA":
        return c == "CA"
    else:
        # Match exact country code
        return c == r
