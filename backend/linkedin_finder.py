import re
import time
from typing import Dict, Any, Optional
from ddgs import DDGS

# Cache to prevent repeated searches for the same brand
DECISION_MAKER_CACHE: Dict[str, Dict[str, Any]] = {}

INVALID_NAME_WORDS = {
    'and', 'or', 'of', 'the', 'a', 'an', 'is', 'was', 'for', 'to', 'in', 'at',
    'by', 'from', 'with', 'ceo', 'founder', 'owner', 'president', 'director',
    'co-founder', 'executive', 'chief', 'officer', 'company', 'brand', 'store',
    'about', 'meet', 'our', 'story', 'official', 'online', 'shop', 'team'
}

def is_valid_human_name(name: str) -> bool:
    if not name or len(name) < 3 or len(name) > 40:
        return False
    tokens = name.split()
    if len(tokens) < 2 or len(tokens) > 4:
        return False
    # Check if first or last token is an invalid word
    if tokens[0].lower() in INVALID_NAME_WORDS or tokens[-1].lower() in INVALID_NAME_WORDS:
        return False
    for t in tokens:
        if not re.match(r"^[A-Z][a-zA-Z'\.\-]*$", t):
            return False
    return True

def clean_person_name(raw_title: str, brand_name: str) -> str:
    """Extract clean person name from SERP / LinkedIn title."""
    if not raw_title:
        return ""

    # Split by standard title separators
    parts = re.split(r'\s+[-–|—]\s+', raw_title)
    if not parts:
        return ""

    candidate = parts[0].strip()
    candidate = re.sub(r'\s*\|\s*LinkedIn.*$', '', candidate, flags=re.IGNORECASE).strip()
    candidate = re.sub(r'\s*-\s*LinkedIn.*$', '', candidate, flags=re.IGNORECASE).strip()

    # If the candidate name matches brand name, check second part
    if candidate.lower() == brand_name.lower():
        if len(parts) > 1 and not any(kw in parts[1].lower() for kw in ['linkedin', 'company', 'overview']):
            candidate = parts[1].strip()
        else:
            return ""

    # Validate name tokens
    tokens = candidate.split()
    if 2 <= len(tokens) <= 4:
        if all(re.match(r"^[A-Za-z'\.\-]+$", t) for t in tokens):
            if tokens[0].lower() not in INVALID_NAME_WORDS and tokens[-1].lower() not in INVALID_NAME_WORDS:
                return candidate

    return ""

def find_decision_maker(brand_name: str, delay_seconds: float = 0.1) -> Dict[str, Any]:
    """
    Find founder/CEO/owner for a brand using natural language search queries.
    """
    if not brand_name or not brand_name.strip():
        return {
            "founder_name": "Not Found",
            "linkedin_url": "Not Found",
            "role_title": "",
            "status": "Not Found"
        }

    brand_clean = brand_name.strip()
    cache_key = brand_clean.lower()

    if cache_key in DECISION_MAKER_CACHE:
        return DECISION_MAKER_CACHE[cache_key]

    # Two targeted natural language queries
    queries = [
        f"{brand_clean} founder linkedin",
        f"{brand_clean} CEO linkedin"
    ]

    ddgs = DDGS(timeout=4)

    for q in queries:
        try:
            time.sleep(delay_seconds)
            results = list(ddgs.text(q, max_results=4))
            for item in results:
                title = item.get('title', '')
                href = item.get('href', '')
                snippet = item.get('body', '')

                # 1. Direct LinkedIn profile link
                if 'linkedin.com/in/' in href:
                    person_name = clean_person_name(title, brand_clean)
                    if not person_name:
                        # Try to extract name from URL path: e.g. /in/john-smith-123
                        m_url = re.search(r'/in/([a-zA-Z0-9\-]+)', href)
                        if m_url:
                            raw_slug = m_url.group(1).split('-')
                            name_words = [w.capitalize() for w in raw_slug if not w.isdigit() and len(w) > 1]
                            if 2 <= len(name_words) <= 3:
                                person_name = " ".join(name_words)

                    if person_name:
                        role = "Founder / Executive"
                        title_parts = re.split(r'\s+[-–|—]\s+', title)
                        if len(title_parts) > 1:
                            role = title_parts[1].replace('| LinkedIn', '').replace('LinkedIn', '').strip()

                        result = {
                            "founder_name": person_name,
                            "linkedin_url": href,
                            "role_title": role,
                            "status": "Found"
                        }
                        DECISION_MAKER_CACHE[cache_key] = result
                        return result

                # 2. Extract name from snippet (e.g. "founders Marianna Hewitt and Lauren Ireland", "founded by John Doe")
                m_found = re.search(r'(?:founders|founder|founded by|co-founder)\s+([A-Z][a-z]+\s+[A-Z][a-z]+)', snippet)
                if m_found:
                    candidate = m_found.group(1).strip()
                    if is_valid_human_name(candidate):
                        # Quick targeted search for their linkedin profile
                        try:
                            time.sleep(0.2)
                            sub_res = list(ddgs.text(f"{candidate} {brand_clean} linkedin", max_results=2))
                            for sub in sub_res:
                                if 'linkedin.com/in/' in sub.get('href', ''):
                                    result = {
                                        "founder_name": candidate,
                                        "linkedin_url": sub.get('href'),
                                        "role_title": "Founder",
                                        "status": "Found"
                                    }
                                    DECISION_MAKER_CACHE[cache_key] = result
                                    return result
                        except Exception:
                            pass

                        result = {
                            "founder_name": candidate,
                            "linkedin_url": "Not Found",
                            "role_title": "Founder",
                            "status": "Founder Name Only"
                        }
                        DECISION_MAKER_CACHE[cache_key] = result
                        return result

        except Exception:
            continue

    return {
        "founder_name": "Not Found",
        "linkedin_url": "Not Found",
        "role_title": "",
        "status": "Not Found"
    }
