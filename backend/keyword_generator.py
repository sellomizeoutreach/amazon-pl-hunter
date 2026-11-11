"""
Automatic Keyword Generator for Amazon Private Label Hunter
------------------------------------------------------------
Auto-discovers fresh, niche-specific Amazon search keywords every run
without any manual input. Uses three free, zero-cost sources:

  1. Amazon Best Sellers pages (amazon.com/gp/bestsellers/<category>) —
     crawls the top product categories, extracts real product titles from
     the product-link anchor text, and mines them into clean keyword phrases.

  2. Amazon Search Autocomplete API (completion?search-alias=aps&q=<seed>) —
     free JSON endpoint that returns real buyer search suggestions for each
     seed niche. Gives fresh, demand-proven long-tail phrases with zero scraping.

  3. DuckDuckGo Search (DDGS) fallback — searches for trending PL niche lists
     and parses result snippets for actionable product keyword phrases.

Output: a deduplicated list of clean lowercase search keyword strings,
ready to feed directly into auto_hunter.py → run_pipeline().

Design Principles:
  - 100% free, no paid APIs, no Selenium required
  - Polite rate-limiting between requests
  - Graceful fallback chain: Amazon BSR → Amazon Autocomplete → DDGS → Evergreen seeds
  - Each keyword is a 2-5 word product search phrase (not a broad category)
  - Keywords rotate daily via deterministic hash so each run explores fresh niches
  - Merged with any user-added lines in keywords.txt (file no longer required)
"""

import re
import os
import json
import time
import random
import hashlib
import warnings
from datetime import datetime, date
from typing import List, Optional, Set
from urllib.parse import urljoin, quote_plus

# Silence duckduckgo_search package-rename warning
warnings.filterwarnings("ignore", category=RuntimeWarning, module="duckduckgo_search")
warnings.filterwarnings("ignore", category=RuntimeWarning, module="ddgs")

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from curl_cffi import requests as cffi_requests
    HAS_CFFI = True
except ImportError:
    HAS_CFFI = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
    HAS_DDGS = True
except ImportError:
    HAS_DDGS = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYWORDS_FILE = os.path.join(ROOT_DIR, "keywords.txt")
KW_CACHE_FILE = os.path.join(ROOT_DIR, "data", "keyword_cache.json")

# Amazon Best Sellers category paths — covers main PL-friendly departments
BSR_CATEGORIES = [
    "/gp/bestsellers/kitchen/",
    "/gp/bestsellers/sporting-goods/",
    "/gp/bestsellers/pet-supplies/",
    "/gp/bestsellers/health/",
    "/gp/bestsellers/beauty/",
    "/gp/bestsellers/office-products/",
    "/gp/bestsellers/tools/",
    "/gp/bestsellers/baby-products/",
    "/gp/bestsellers/toys-and-games/",
    "/gp/bestsellers/outdoor/",
    "/gp/bestsellers/home-garden/",
    "/gp/bestsellers/luggage/",
]

# Seed terms for the Amazon autocomplete API — broad product niches that
# generate dozens of real long-tail phrases each
AUTOCOMPLETE_SEEDS = [
    # Kitchen & Home
    "silicone kitchen", "bamboo kitchen", "stainless steel kitchen", "kitchen organizer",
    "food storage container", "coffee maker portable", "blender personal",
    "cutting board", "knife set kitchen", "spice organizer",
    # Health & Fitness
    "resistance band", "foam roller", "yoga mat", "posture corrector",
    "massage gun", "pull up bar", "jump rope weighted", "ab roller",
    # Pet
    "dog grooming", "cat litter mat", "dog slow feeder", "pet water fountain",
    "dog harness no pull", "cat tree", "dog treat puzzle",
    # Outdoor & Sports
    "camping hammock", "hiking backpack", "water bottle insulated", "tent lightweight",
    "fishing tackle", "bike accessories", "running belt",
    # Baby & Kids
    "baby food maker", "diaper bag backpack", "baby monitor", "toddler backpack",
    "kids art supply", "baby carrier ergonomic",
    # Office & Desk
    "laptop stand adjustable", "desk organizer", "cable management",
    "monitor riser", "wrist rest mouse pad", "standing desk mat",
    # Beauty & Personal
    "jade roller", "gua sha", "eyelash curler", "makeup organizer",
    "hair diffuser", "nail kit", "beard grooming",
    # Travel
    "packing cubes", "travel toiletry bag", "passport holder", "luggage scale",
    "neck pillow travel", "travel umbrella",
]

# DDGS search queries to find trending PL niches
DDGS_QUERIES = [
    f"best amazon private label product ideas {datetime.now().year}",
    f"trending amazon FBA niche products {datetime.now().year}",
    "low competition amazon private label products under 100 reviews",
    "amazon product research underserved niche 2024 2025",
    "best selling amazon products new brand opportunity",
]

# Evergreen seed keywords — daily-rotated final fallback guarantee
# These are specific product phrases (not broad categories)
SEED_KEYWORDS_EVERGREEN = [
    "silicone kitchen utensils set",
    "bamboo drawer organizer set",
    "yoga mat non slip thick",
    "travel packing cubes lightweight",
    "posture corrector back brace",
    "pet grooming brush self cleaning",
    "desk cable management box",
    "camping hammock lightweight portable",
    "foam roller high density",
    "kitchen herb garden starter kit",
    "reusable silicone food storage bags",
    "adjustable laptop stand ergonomic",
    "resistance bands set workout",
    "essential oil diffuser ultrasonic",
    "meal prep containers glass lid",
    "cat litter mat waterproof",
    "dog slow feeder bowl puzzle",
    "baby food storage containers",
    "travel toiletry organizer bag",
    "microfiber cleaning cloths set",
    "wooden cutting board handle",
    "cold brew coffee maker portable",
    "shower caddy rust proof",
    "under desk footrest ergonomic",
    "magnetic knife strip wall mount",
    "silicone baking mat non stick",
    "stainless steel water bottle insulated",
    "car phone mount dashboard",
    "portable blender usb rechargeable",
    "plant watering globes self watering",
    "garden kneeler pad foam",
    "kids art supply organizer",
    "bathroom shelf over toilet",
    "weighted sleep mask women",
    "dog harness no pull adjustable",
    "cat tree condo scratching post",
    "bike handlebar bag waterproof",
    "standing desk mat anti fatigue",
    "monitor riser wood",
    "hair diffuser curly hair",
    "beard grooming kit men",
    "jade roller face gua sha",
    "eyelash curler heated",
    "passport holder rfid blocking",
    "luggage scale digital",
    "neck pillow memory foam",
    "packing cubes compression",
    "diaper bag backpack large",
    "baby carrier ergonomic newborn",
    "toddler backpack harness",
]

# Tokens that signal Amazon UI noise (not product titles)
UI_NOISE_PATTERNS = [
    r'\d+\.\d+\s+out\s+of',         # "4.5 out of 5 stars"
    r'out\s+of\s+\d+\s+stars?',      # "out of 5 stars"
    r'stars?\s*\d+',                  # "stars 42"
    r'\d+\s*stars?',                  # "42 stars"
    r'offers?\s+from',                # "offers from $X"
    r'pkr\s*[\d,]+',                  # Pakistani Rupee noise
    r'^\$[\d,\.]+',                   # starts with price
    r'^\d+\s+offer',                  # "1 offer from..."
    r'check each product page',
    r'eligible for free shipping',
    r'amazon\'?s choice',
    r'best seller',
    r'limited time deal',
    r'lightning deal',
    r'sponsored',
    r'#\d+\s+in\b',                   # "#1 in Kitchen"
    r'\breload your balance\b',
    r'\bamazon business card\b',
    r'\bsee all\b',
    r'\bmore results\b',
    r'\bdeals\b.*\bhome\b',
]

# Stop-words that make a phrase too generic
GENERIC_STOP_WORDS = {
    "amazon", "best", "top", "buy", "shop", "deals", "sale", "prime",
    "review", "reviews", "rating", "seller", "brand", "product", "products",
    "guide", "list", "ideas", "things", "stuff", "items", "category",
    "department", "gift", "gifts", "new", "popular", "trending", "featured",
    "recommended", "editors", "choice", "pick", "picks",
}

MIN_KW_TOKENS = 2
MAX_KW_TOKENS = 6

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


def _get_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    }


def _fetch_html(url: str, timeout: int = 15) -> Optional[str]:
    """Fetch a URL using curl_cffi (preferred) or requests fallback. Returns HTML or None."""
    try:
        if HAS_CFFI:
            resp = cffi_requests.get(
                url, headers=_get_headers(), timeout=timeout, impersonate="chrome110"
            )
            if resp.status_code == 200:
                return resp.text
    except Exception:
        pass
    try:
        if HAS_REQUESTS:
            resp = requests.get(url, headers=_get_headers(), timeout=timeout)
            if resp.status_code == 200:
                return resp.text
    except Exception:
        pass
    return None


def _fetch_json(url: str, timeout: int = 10) -> Optional[dict]:
    """Fetch and parse a JSON endpoint."""
    hdrs = {**_get_headers(), "Accept": "application/json, text/javascript, */*; q=0.01"}
    try:
        if HAS_CFFI:
            resp = cffi_requests.get(url, headers=hdrs, timeout=timeout, impersonate="chrome110")
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    try:
        if HAS_REQUESTS:
            resp = requests.get(url, headers=hdrs, timeout=timeout)
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Keyword cleaning & validation
# ---------------------------------------------------------------------------

def _is_ui_noise(text: str) -> bool:
    """Returns True if the text string looks like Amazon UI metadata, not a product title."""
    text_lower = text.lower().strip()
    for pat in UI_NOISE_PATTERNS:
        if re.search(pat, text_lower):
            return True
    return False


def _clean_product_title(title: str) -> Optional[str]:
    """
    Extracts a clean 2-5 token keyword phrase from a raw Amazon product title.
    Returns None if the title looks like UI noise, a broad category, or is too short/long.

    E.g.:
      "Bamboo Drawer Organizer, Set of 4 - Adjustable..." → "bamboo drawer organizer"
      "4.5 out of 5 stars 42,312"                         → None  (noise)
      "Kitchen"                                            → None  (too short / category)
    """
    if not title or not isinstance(title, str):
        return None

    # Quick noise pre-check on raw string
    if _is_ui_noise(title):
        return None

    # Must be a reasonable product title length
    if len(title) < 12 or len(title) > 200:
        return None

    # Strip parenthetical/bracket asides and punctuation
    cleaned = re.sub(r'\[.*?\]|\(.*?\)', '', title)
    cleaned = re.sub(r'["\',\-–|/\\!@#]', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip().lower()

    # Hard-reject if any digit remains after the above (price, rating, model number)
    # Exception: allow digits in known compound words like "2-in-1", "3d", "360"
    # Strategy: split to tokens and reject digit-heavy ones
    tokens_raw = cleaned.split()
    tokens = []
    for t in tokens_raw:
        # skip purely numeric / price tokens
        if re.match(r'^[\d\.\$\%\,]+$', t):
            continue
        # skip tokens that are mostly digits (e.g. "b07xyzabc", "24oz", "12pack")
        digit_count = sum(1 for c in t if c.isdigit())
        if len(t) > 0 and digit_count / len(t) > 0.5:
            continue
        # skip very short tokens
        if len(t) <= 2:
            continue
        tokens.append(t)

    # Remove common filler words
    filler = {
        'pack', 'set', 'kit', 'oz', 'ml', 'lb', 'lbs', 'kg', 'cm', 'inch', 'inches',
        'count', 'pcs', 'piece', 'pieces', 'ct', 'qty', 'with', 'for', 'and',
        'the', 'a', 'an', 'of', 'by', 'in', 'to', 'or', 'is', 'not', 'new',
        'buy', 'get', 'free', 'shipping', 'prime', 'sold', 'per', 'each',
        'color', 'size', 'style', 'type', 'model', 'series',
    }
    tokens = [t for t in tokens if t not in filler]

    if len(tokens) < MIN_KW_TOKENS:
        return None

    # Build 3-4 token phrase (enough to be specific, not so long it's too narrow)
    phrase = " ".join(tokens[:4])

    # Reject if phrase is dominated by generic stop-words
    phrase_set = set(phrase.split())
    overlap = phrase_set & GENERIC_STOP_WORDS
    if len(overlap) >= len(phrase_set) - 1:
        return None

    # Final check: phrase must still look clean (no stray digits)
    if re.search(r'\d', phrase):
        return None

    num_tokens = len(phrase.split())
    if num_tokens < MIN_KW_TOKENS or num_tokens > MAX_KW_TOKENS:
        return None

    return phrase


# ---------------------------------------------------------------------------
# Daily rotation helper
# ---------------------------------------------------------------------------

def _daily_subset(items: List, count: int, salt: str = "") -> List:
    """
    Returns a deterministic but day-rotating subset of `count` items.
    Changes each calendar day so successive runs explore different niches.
    """
    today_str = str(date.today()) + salt
    seed_int = int(hashlib.md5(today_str.encode()).hexdigest(), 16) % (10 ** 9)
    rng = random.Random(seed_int)
    shuffled = items[:]
    rng.shuffle(shuffled)
    return shuffled[:count]


# ---------------------------------------------------------------------------
# Source 1: Amazon Best Sellers (product title extraction via /dp/ links)
# ---------------------------------------------------------------------------

def _keywords_from_amazon_bsr(marketplace: str = "amazon.com", max_categories: int = 5) -> List[str]:
    """
    Crawls a daily-rotated selection of Amazon Best Sellers pages.
    Extracts product titles by selecting all <a href*="/dp/"> anchor texts
    (server-rendered on BSR pages unlike Movers & Shakers which is JS-rendered).
    """
    if not HAS_BS4:
        return []

    base_url = f"https://www.{marketplace}"
    categories = _daily_subset(BSR_CATEGORIES, max_categories, salt="bsr")
    keywords = []

    for cat_path in categories:
        url = urljoin(base_url, cat_path)
        print(f"  [KeyGen] BSR → {url}")
        html = _fetch_html(url)
        if not html:
            print(f"  [KeyGen] BSR fetch blocked/failed for {cat_path}")
            time.sleep(2.0)
            continue

        soup = BeautifulSoup(html, "html.parser")
        seen_titles: Set[str] = set()
        cat_kws = []

        # Primary: product links (/dp/ URLs) with product-title anchor text
        for a in soup.select('a[href*="/dp/"]'):
            text = a.get_text(separator=" ", strip=True)
            if text in seen_titles:
                continue
            seen_titles.add(text)
            kw = _clean_product_title(text)
            if kw:
                cat_kws.append(kw)

        # Secondary: any span inside zg-grid divs with reasonable text
        if len(cat_kws) < 5:
            for span in soup.select('div[id*="gridItemRoot"] span, div[class*="zg-grid"] span'):
                text = span.get_text(strip=True)
                if text in seen_titles:
                    continue
                seen_titles.add(text)
                kw = _clean_product_title(text)
                if kw:
                    cat_kws.append(kw)

        print(f"  [KeyGen] BSR → {len(cat_kws)} clean keywords from {cat_path}")
        keywords.extend(cat_kws)
        time.sleep(random.uniform(2.0, 3.5))

    return keywords


# ---------------------------------------------------------------------------
# Source 2: Amazon Search Autocomplete API (free, JSON, no scraping needed)
# ---------------------------------------------------------------------------

def _keywords_from_autocomplete(
    marketplace: str = "amazon.com",
    max_seeds: int = 15,
) -> List[str]:
    """
    Queries Amazon's public search autocomplete/suggestions API for each seed niche.
    Returns real buyer-typed search phrases — demand-proven long-tail keywords,
    no paid tool or scraping required.

    Working endpoint (public, no auth required):
      https://completion.amazon.com/api/2017/suggestions
        ?limit=10&prefix=<query>&suggestion-type=KEYWORD&page-type=Search
        &alias=aps&site-variant=desktop&version=3&event=onKeyPress
        &mid=ATVPDKIKX0DER&plain-mid=1&client-info=amazon-search-ui

    Returns JSON: {"suggestions": [{"value": "yoga mat non slip", ...}, ...]}
    """
    seeds = _daily_subset(AUTOCOMPLETE_SEEDS, max_seeds, salt="autocomplete")
    keywords = []

    # Marketplace → Amazon mid (MarketplaceID) mapping
    MKT_MID = {
        "amazon.com":    ("ATVPDKIKX0DER", "1"),
        "amazon.co.uk":  ("A1F83G8C2ARO7P", "3"),
        "amazon.de":     ("A1PA6795UKMFR9", "4"),
        "amazon.fr":     ("A13V1IB3VIYZZH", "5"),
        "amazon.co.jp":  ("A1VC38T7YXB528", "6"),
        "amazon.ca":     ("A2EUQ1WTGCTBG2", "7"),
        "amazon.it":     ("APJ6JRA9NG5V4",  "35691"),
        "amazon.es":     ("A1RKKUPIHCS9HS", "44551"),
        "amazon.in":     ("A21TJRUUN4KGV",  "44571"),
        "amazon.com.au": ("A39IBJ37TRP1C6", "126120"),
    }
    mid, _ = MKT_MID.get(marketplace, ("ATVPDKIKX0DER", "1"))

    base = "https://completion.amazon.com/api/2017/suggestions"

    hdrs = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://www.{marketplace}/",
    }

    for seed in seeds:
        url = (
            f"{base}?limit=10"
            f"&prefix={quote_plus(seed)}"
            f"&suggestion-type=KEYWORD"
            f"&page-type=Search"
            f"&alias=aps"
            f"&site-variant=desktop"
            f"&version=3"
            f"&event=onKeyPress"
            f"&wc="
            f"&lop=en_US"
            f"&mid={mid}"
            f"&plain-mid=1"
            f"&client-info=amazon-search-ui"
        )
        try:
            data = None
            if HAS_CFFI:
                resp = cffi_requests.get(url, headers=hdrs, timeout=8, impersonate="chrome110")
                if resp.status_code == 200:
                    data = resp.json()
            if data is None and HAS_REQUESTS:
                resp = requests.get(url, headers=hdrs, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()

            if data and isinstance(data, dict):
                suggestions = data.get("suggestions", [])
                for item in suggestions:
                    value = item.get("value", "") if isinstance(item, dict) else str(item)
                    kw = _clean_product_title(value)
                    if kw:
                        keywords.append(kw)

            time.sleep(random.uniform(0.5, 1.2))

        except Exception as e:
            print(f"  [KeyGen] Autocomplete error for '{seed}': {e}")

    print(f"  [KeyGen] Autocomplete → {len(keywords)} suggestions from {len(seeds)} seed queries")
    return keywords


# ---------------------------------------------------------------------------
# Source 3: DuckDuckGo Search Fallback
# ---------------------------------------------------------------------------

PL_ADJECTIVES = {
    "silicone", "bamboo", "stainless", "wooden", "leather", "canvas",
    "glass", "ceramic", "cotton", "linen", "foam", "rubber", "nylon",
    "waterproof", "reusable", "foldable", "collapsible", "portable",
    "adjustable", "ergonomic", "magnetic", "electric", "rechargeable",
    "compact", "lightweight", "insulated", "airtight", "non-slip",
    "anti", "natural", "organic", "eco", "washable",
}


def _extract_keywords_from_ddgs_snippets(snippets: List[str]) -> List[str]:
    """Mines DuckDuckGo search result snippets for PL niche keyword phrases."""
    keywords = []
    combined = " ".join(snippets).lower()

    # Pattern: "<adjective> <noun phrase>"
    pat = r'\b(' + '|'.join(re.escape(a) for a in PL_ADJECTIVES) + r')[\s\-](\w+(?:\s\w+){0,2})'
    for m in re.finditer(pat, combined):
        kw = _clean_product_title(m.group(0).strip())
        if kw:
            keywords.append(kw)

    # Bullet / numbered list items
    for line in re.split(r'[.\n]', combined):
        line = re.sub(r'^[\s\d\.\-\*\u2022]+', '', line).strip()
        if 10 < len(line) < 80:
            kw = _clean_product_title(line)
            if kw:
                keywords.append(kw)

    return list(dict.fromkeys(keywords))


def _keywords_from_ddgs(max_queries: int = 2) -> List[str]:
    """DuckDuckGo search fallback for trending PL niches."""
    if not HAS_DDGS:
        return []

    queries = _daily_subset(DDGS_QUERIES, max_queries, salt="ddgs")
    snippets = []

    for q in queries:
        print(f"  [KeyGen] DDGS → '{q}'")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with DDGS() as ddgs:
                    results = list(ddgs.text(q, max_results=10))
            for r in results:
                body = r.get("body", "") or r.get("snippet", "")
                title = r.get("title", "")
                snippets.append(f"{title}. {body}")
            time.sleep(random.uniform(1.0, 2.0))
        except Exception as e:
            print(f"  [KeyGen] DDGS error: {e}")

    kws = _extract_keywords_from_ddgs_snippets(snippets)
    print(f"  [KeyGen] DDGS → {len(kws)} candidates")
    return kws


# ---------------------------------------------------------------------------
# Cache layer
# ---------------------------------------------------------------------------

def _load_keyword_cache() -> dict:
    """Return today's keyword cache if it exists and is from today."""
    os.makedirs(os.path.dirname(KW_CACHE_FILE), exist_ok=True)
    if os.path.exists(KW_CACHE_FILE):
        try:
            with open(KW_CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
            if cache.get("date") == str(date.today()):
                return cache
        except Exception:
            pass
    return {}


def _save_keyword_cache(keywords: List[str]):
    """Persist today's generated keywords to disk cache."""
    os.makedirs(os.path.dirname(KW_CACHE_FILE), exist_ok=True)
    try:
        with open(KW_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"date": str(date.today()), "keywords": keywords}, f, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# User keywords.txt merger
# ---------------------------------------------------------------------------

def _load_user_keywords() -> List[str]:
    """
    Loads any manually added keywords from keywords.txt (non-comment lines).
    If the file does not exist, returns an empty list — it is no longer required.
    """
    if not os.path.exists(KEYWORDS_FILE):
        return []
    try:
        with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
            return [
                line.strip().lower()
                for line in f
                if line.strip() and not line.strip().startswith("#")
            ]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

def generate_keywords(
    marketplace: str = "amazon.com",
    target_count: int = 30,
    use_cache: bool = True,
    force_refresh: bool = False,
    include_seeds: bool = True,
    verbose: bool = True,
) -> List[str]:
    """
    Main entry point. Generates a fresh, deduplicated list of Amazon PL search
    keywords automatically — zero manual input required.

    Discovery pipeline (in order):
      1. Return today's cache if available (unless force_refresh=True)
      2. Amazon Best Sellers — product titles via /dp/ anchor text
      3. Amazon Search Autocomplete API — real buyer-typed phrase suggestions
      4. DuckDuckGo Search — trending PL niche lists from web
      5. Merge with user-defined keywords from keywords.txt
      6. Pad to target_count with daily-rotated evergreen seeds
      7. Cache result for the rest of today

    Args:
        marketplace:   Amazon domain, e.g. "amazon.com" or "amazon.co.uk"
        target_count:  Minimum keyword phrases to return
        use_cache:     Use today's cached keywords if available (default True)
        force_refresh: Bypass cache and re-crawl all sources (default False)
        include_seeds: Always include some evergreen seeds (default True)
        verbose:       Print progress to stdout (default True)

    Returns:
        List of clean lowercase 2-5 word keyword phrases
    """
    if verbose:
        print(f"\n[KeyGen] Auto-generating keywords for {marketplace} (date: {date.today()})...")

    # 1. Cache check
    if use_cache and not force_refresh:
        cache = _load_keyword_cache()
        if cache.get("keywords"):
            cached = cache["keywords"]
            user_kws = _load_user_keywords()
            merged = list(dict.fromkeys(user_kws + cached))
            if verbose:
                print(f"[KeyGen] Loaded {len(merged)} keywords from today's cache + user list.")
            return merged[:max(target_count, len(merged))]

    all_raw: List[str] = []

    # 2. Amazon Best Sellers
    try:
        bsr = _keywords_from_amazon_bsr(marketplace=marketplace, max_categories=5)
        all_raw.extend(bsr)
        if verbose:
            print(f"[KeyGen] Amazon BSR contributed {len(bsr)} candidates.")
    except Exception as e:
        if verbose:
            print(f"[KeyGen] BSR source error: {e}")

    # 3. Amazon Autocomplete API
    try:
        auto = _keywords_from_autocomplete(marketplace=marketplace, max_seeds=15)
        all_raw.extend(auto)
        if verbose:
            print(f"[KeyGen] Amazon Autocomplete contributed {len(auto)} candidates.")
    except Exception as e:
        if verbose:
            print(f"[KeyGen] Autocomplete source error: {e}")

    # 4. DDGS fallback (always adds diversity, even if BSR worked)
    try:
        ddgs = _keywords_from_ddgs(max_queries=2)
        all_raw.extend(ddgs)
        if verbose:
            print(f"[KeyGen] DDGS contributed {len(ddgs)} candidates.")
    except Exception as e:
        if verbose:
            print(f"[KeyGen] DDGS source error: {e}")

    # 5. Merge user keywords (take priority at front)
    user_kws = _load_user_keywords()
    if user_kws and verbose:
        print(f"[KeyGen] Merged {len(user_kws)} user keywords from keywords.txt.")
    all_raw = user_kws + all_raw

    # 6. Deduplicate (order-preserving)
    seen: Set[str] = set()
    deduped: List[str] = []
    for kw in all_raw:
        kw_l = kw.lower().strip()
        if kw_l and kw_l not in seen:
            seen.add(kw_l)
            deduped.append(kw_l)

    # 7. Pad with rotating evergreen seeds if below target
    if include_seeds or len(deduped) < target_count:
        needed = max(10, target_count - len(deduped))
        seed_pool = [s for s in SEED_KEYWORDS_EVERGREEN if s not in seen]
        for s in _daily_subset(seed_pool, min(needed, len(seed_pool)), salt="seed"):
            if s not in seen:
                seen.add(s)
                deduped.append(s)

    if verbose:
        print(f"[KeyGen] Final keyword pool: {len(deduped)} unique phrases.")

    # 8. Cache for today
    _save_keyword_cache(deduped)

    return deduped


def refresh_keywords_file(
    marketplace: str = "amazon.com",
    target_count: int = 30,
    verbose: bool = True,
) -> List[str]:
    """
    Generates fresh keywords and rewrites keywords.txt with the auto-generated list.
    Preserves any existing #comment lines the user has added.
    Returns the final keyword list.
    """
    kws = generate_keywords(
        marketplace=marketplace,
        target_count=target_count,
        use_cache=False,
        force_refresh=True,
        verbose=verbose,
    )

    # Preserve comment lines
    comment_lines = []
    if os.path.exists(KEYWORDS_FILE):
        try:
            with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("#"):
                        comment_lines.append(line.rstrip())
        except Exception:
            pass

    try:
        with open(KEYWORDS_FILE, "w", encoding="utf-8") as f:
            if comment_lines:
                f.write("\n".join(comment_lines) + "\n\n")
            f.write(f"# Auto-generated {date.today()} — edit above this line or add your own niches\n")
            f.write("\n".join(kws) + "\n")
        if verbose:
            print(f"[KeyGen] Wrote {len(kws)} keywords to {KEYWORDS_FILE}")
    except Exception as e:
        if verbose:
            print(f"[KeyGen] Could not write keywords.txt: {e}")

    return kws


if __name__ == "__main__":
    import sys
    force = "--refresh" in sys.argv
    kws = generate_keywords(force_refresh=force, verbose=True)
    print(f"\n--- KEYWORD PREVIEW (first 25 of {len(kws)}) ---")
    for i, k in enumerate(kws[:25], 1):
        print(f"  {i:2d}. {k}")
