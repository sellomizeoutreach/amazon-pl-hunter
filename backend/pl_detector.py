import re
import unicodedata
from difflib import SequenceMatcher
from typing import List, Dict, Any, Tuple

# Comprehensive list of major corporate / wholesale / conglomerate brands to NEGATE
GLOBAL_MEGABRANDS = {
    # Beauty & Personal Care
    "l'oreal", "loreal", "maybelline", "cerave", "neutrogena", "olay", "dove",
    "nivea", "garnier", "pantene", "head & shoulders", "tresemme", "colgate",
    "crest", "oral-b", "oral b", "gillette", "schick", "bic", "vaseline",
    "aveeno", "cetaphil", "eucerin", "la roche-posay", "la roche posay",
    "revlon", "covergirl", "nyx", "elf", "e.l.f.", "burts bees", "burt's bees",
    "clinique", "estee lauder", "mac", "urban decay", "bath & body works",
    "johnson & johnson", "johnson's", "ogx", "clean & clear",
    "old spice", "arm & hammer", "arm and hammer", "secret", "degree", "axe",
    "suave", "speed stick", "irish spring", "dial", "tom's of maine", "toms of maine",
    "mitchum", "ban", "right guard", "lady speed stick", "dove men+care", "dove men",
    "dr teal's", "dr teals", "degree men", "degree women", "harry's", "harrys",
    # Electronics & Tech
    "apple", "samsung", "sony", "bose", "jbl", "beats", "sennheiser",
    "logitech", "canon", "nikon", "hp", "dell", "lenovo", "asus", "acer",
    "microsoft", "google", "belkin", "sandisk", "western digital",
    "seagate", "kingston", "philips", "panasonic", "toshiba", "lg", "fitbit",
    # Apparel & Footwear
    "nike", "adidas", "under armour", "puma", "reebok", "new balance",
    "champion", "levis", "levi's", "calvin klein", "tommy hilfiger",
    "ralph lauren", "hanes", "fruit of the loom", "crocs", "skechers",
    "columbia", "the north face", "patagonia", "carhartt",
    # Home & Kitchen
    "dyson", "shark", "ninja", "keurig", "nespresso", "cuisinart",
    "kitchenaid", "instant pot", "irobot", "roomba", "stanley", "yeti",
    "hydro flask", "oxo", "pyrex", "rubbermaid", "tupperware", "brita",
    # Amazon Private Brands (Not independent 3P PL)
    "amazon basics", "amazonbasics", "amazon essentials", "solimo",
    "amazon commercial", "presto!", "pinzon", "goodthreads", "daily ritual"
}

# Generic words that do not count as a brand identifier
COMMON_STOP_WORDS = {
    'the', 'a', 'an', 'and', 'or', 'of', 'for', 'in', 'to', 'with', 'by', 'on', 'at', 'from',
    'llc', 'inc', 'ltd', 'limited', 'corp', 'corporation', 'co', 'company', 'gmbh',
    'direct', 'official', 'store', 'shop', 'retail', 'online', 'trade', 'trading',
    'global', 'international', 'group', 'enterprises', 'solutions', 'products', 'goods',
    'brand', 'brands', 'us', 'usa', 'uk', 'de', 'ca', 'fr', 'eu', 'tech', 'technology',
    'home', 'life', 'care', 'beauty', 'fashion', 'item', 'items', 'selection'
}

def is_megabrand_or_corporate(brand_name: str) -> bool:
    """Check if brand is a multi-billion dollar corporate brand or Amazon owned brand."""
    if not brand_name:
        return False
    norm = brand_name.lower().strip()
    norm = re.sub(r'[^a-z0-9\s]', '', norm)
    
    for mb in GLOBAL_MEGABRANDS:
        clean_mb = re.sub(r'[^a-z0-9\s]', '', mb)
        if norm == clean_mb or norm.startswith(clean_mb + " ") or norm.endswith(" " + clean_mb):
            return True
    return False

def extract_meaningful_words(text: str) -> List[str]:
    """Extract clean words with punctuation removed, ignoring common corporate/filler stop-words."""
    if not text:
        return []
    text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('utf-8').lower()
    raw_tokens = re.findall(r'[a-z0-9]{3,}', text)
    return [t for t in raw_tokens if t not in COMMON_STOP_WORDS]

def check_name_match(brand_name: str, seller_name: str) -> Tuple[bool, float, str]:
    """
    Lenient word resemblance check:
    At least ONE meaningful word from the brand name must match the seller name (or vice versa),
    with support for compact substrings, token overlap, and fuzzy resemblance.
    """
    if not brand_name or not seller_name:
        return False, 0.0, "missing_data"

    brand_words = extract_meaningful_words(brand_name)
    seller_words = extract_meaningful_words(seller_name)

    # Normalized compact representations (all alphanumeric without spaces)
    clean_brand = re.sub(r'[^a-z0-9]', '', brand_name.lower())
    clean_seller = re.sub(r'[^a-z0-9]', '', seller_name.lower())

    # 1. Exact compact match or direct substring
    # e.g. "haoyuyan" in "haoyuyanus1wq" or "lamicall" in "shenzhenlamicalltech"
    if clean_brand and clean_seller:
        if clean_brand == clean_seller:
            return True, 1.0, "exact_match"
        for bw in brand_words:
            if bw in clean_seller:
                return True, 0.95, f"word_in_seller ('{bw}')"
        for sw in seller_words:
            if sw in clean_brand:
                return True, 0.95, f"seller_word_in_brand ('{sw}')"

    # 2. Token overlap: at least one meaningful word matches
    overlap = set(brand_words) & set(seller_words)
    if overlap:
        matched_word = list(overlap)[0]
        return True, 0.90, f"shared_word ('{matched_word}')"

    # 3. Fuzzy match on individual words (handles plurals, minor spelling variations)
    for bw in brand_words:
        for sw in seller_words:
            if len(bw) >= 4 and len(sw) >= 4:
                if bw.startswith(sw) or sw.startswith(bw):
                    return True, 0.85, f"stem_match ('{bw}' ~ '{sw}')"
                sim = SequenceMatcher(None, bw, sw).ratio()
                if sim >= 0.78:
                    return True, sim, f"fuzzy_word ('{bw}' ~ '{sw}', {int(sim*100)}%)"

    return False, 0.0, "no_word_resemblance"

def evaluate_private_label(
    brand_name: str,
    buybox_seller: str,
    all_sellers: List[str],
    has_brand_store: bool = False,
    has_aplus_content: bool = False,
    total_offers_count: int = 1
) -> Dict[str, Any]:
    """
    Intelligent & Lenient Private Label evaluation:
    - Negates corporate megabrands & Amazon 1P retail.
    - Requires at least ONE shared/resembling word between brand and seller.
    - Allows up to 5-6 sellers if the brand owner is present in the seller roster.
    - Detects official Amazon Brand Store & A+ Content as strong PL indicators.
    """
    brand_clean = brand_name.strip() if brand_name else ""
    buybox_clean = buybox_seller.strip() if buybox_seller else ""

    # Clean and deduplicate seller list
    seen_s = set()
    cleaned_sellers = []
    for s in ([buybox_clean] + (all_sellers or [])):
        s_clean = s.strip()
        if s_clean and s_clean.lower() not in seen_s:
            seen_s.add(s_clean.lower())
            cleaned_sellers.append(s_clean)

    effective_seller_count = max(len(cleaned_sellers), total_offers_count)

    # --- NEGATION 1: Global Megabrands ---
    if is_megabrand_or_corporate(brand_clean):
        return {
            "is_private_label": False,
            "confidence": "Negated",
            "matched_seller": "",
            "seller_match_type": "none",
            "match_reason": f"NEGATED: Major corporate/enterprise brand ({brand_clean})",
            "total_sellers_count": effective_seller_count,
            "all_sellers": cleaned_sellers
        }

    # --- NEGATION 2: Sold by Amazon Retail ---
    if "amazon.com" in buybox_clean.lower() or buybox_clean.lower() == "amazon":
        return {
            "is_private_label": False,
            "confidence": "Negated",
            "matched_seller": "",
            "seller_match_type": "none",
            "match_reason": "NEGATED: Sold by Amazon.com (1P Vendor)",
            "total_sellers_count": effective_seller_count,
            "all_sellers": cleaned_sellers
        }

    # --- CHECK 1: Brand Word Match with Buy Box Seller ---
    if buybox_clean:
        is_match, score, reason = check_name_match(brand_clean, buybox_clean)
        if is_match:
            confidence = "High (Verified PL)"
            if has_brand_store or has_aplus_content:
                confidence = "Ultra High (Brand Registered PL)"
            return {
                "is_private_label": True,
                "confidence": confidence,
                "matched_seller": buybox_clean,
                "seller_match_type": "buybox",
                "match_reason": f"Brand shares word with Buy Box seller ({reason})",
                "total_sellers_count": effective_seller_count,
                "all_sellers": cleaned_sellers
            }

    # --- CHECK 2: Brand Word Match with ANY other seller (up to 5-6 sellers) ---
    for seller in cleaned_sellers:
        is_match, score, reason = check_name_match(brand_clean, seller)
        if is_match:
            return {
                "is_private_label": True,
                "confidence": "Medium-High (PL Owner in Seller List)",
                "matched_seller": seller,
                "seller_match_type": "other_seller",
                "match_reason": f"Brand owner found in seller roster: '{seller}' ({reason})",
                "total_sellers_count": effective_seller_count,
                "all_sellers": cleaned_sellers
            }

    # --- CHECK 3: Low Seller Count (<= 3 Sellers) with Amazon Brand Store or A+ Content ---
    if effective_seller_count <= 3 and (has_brand_store or has_aplus_content):
        primary_seller = cleaned_sellers[0] if cleaned_sellers else (buybox_clean or brand_clean)
        if primary_seller and "amazon" not in primary_seller.lower():
            return {
                "is_private_label": True,
                "confidence": "High (Brand Registered Storefront)",
                "matched_seller": primary_seller,
                "seller_match_type": "brand_store",
                "match_reason": f"Verified Amazon Brand Storefront & A+ Content for '{brand_clean}'",
                "total_sellers_count": effective_seller_count,
                "all_sellers": cleaned_sellers or [primary_seller]
            }

    # --- NEGATION 3: Heavy Multi-Seller Wholesale (6+ sellers or 3+ sellers without brand match) ---
    if effective_seller_count > 5:
        return {
            "is_private_label": False,
            "confidence": "Negated",
            "matched_seller": "",
            "seller_match_type": "none",
            "match_reason": f"NEGATED: Wholesale listing ({effective_seller_count} competing sellers, no brand match)",
            "total_sellers_count": effective_seller_count,
            "all_sellers": cleaned_sellers
        }

    return {
        "is_private_label": False,
        "confidence": "Low",
        "matched_seller": "",
        "seller_match_type": "none",
        "match_reason": f"No seller matches any brand word across {effective_seller_count} seller(s)",
        "total_sellers_count": effective_seller_count,
        "all_sellers": cleaned_sellers
    }
