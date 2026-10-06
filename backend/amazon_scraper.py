import time
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional, Set, Callable
from bs4 import BeautifulSoup
from curl_cffi import requests

from backend.pl_detector import evaluate_private_label, is_megabrand_or_corporate
from backend.linkedin_finder import find_decision_maker

DEFAULT_HEADERS = {
    'Accept-Language': 'en-US,en;q=0.9',
}

import random

def generate_amazon_session_id() -> str:
    """Generate a realistic random Amazon session-id to prevent session-level throttling."""
    return f"{random.randint(100, 999)}-{random.randint(1000000, 9999999)}-{random.randint(1000000, 9999999)}"

class AmazonExtractor:
    def __init__(self, marketplace: str = "amazon.com", delay_between_requests: float = 0.3):
        self.marketplace = marketplace.replace('https://', '').replace('http://', '').strip('/')
        if not self.marketplace.startswith('www.'):
            self.base_url = f"https://www.{self.marketplace}"
        else:
            self.base_url = f"https://{self.marketplace}"
        self.delay = delay_between_requests
        self.seen_brands: Set[str] = set()
        self.cookies = {
            'i18n-prefs': 'USD'
        }

    def build_search_url(self, query_or_url: str, page: int) -> str:
        """Construct valid search URL with standard pagination parameters."""
        query_or_url = query_or_url.strip()
        if query_or_url.startswith('http://') or query_or_url.startswith('https://'):
            parsed = urllib.parse.urlparse(query_or_url)
            qs = urllib.parse.parse_qs(parsed.query)
            qs['page'] = [str(page)]
            qs['ref'] = [f'sr_pg_{page}']
            new_query = urllib.parse.urlencode(qs, doseq=True)
            return urllib.parse.urlunparse(parsed._replace(query=new_query))
        else:
            encoded_k = urllib.parse.quote_plus(query_or_url)
            return f"{self.base_url}/s?k={encoded_k}&page={page}&ref=sr_pg_{page}"

    def fetch_page(self, url: str, max_retries: int = 4) -> Optional[BeautifulSoup]:
        """Fetch URL using curl_cffi Chrome impersonation with rotating session-ids and jittered backoff."""
        impersonations = ["chrome124", "chrome120", "safari15_5", "chrome124"]
        for attempt in range(max_retries + 1):
            imp = impersonations[min(attempt, len(impersonations) - 1)]
            try:
                # Rotate session-id on retry to bypass session-level throttling
                req_cookies = dict(self.cookies)
                req_cookies['session-id'] = generate_amazon_session_id()

                resp = requests.get(
                    url,
                    headers=DEFAULT_HEADERS,
                    cookies=req_cookies,
                    impersonate=imp,
                    timeout=15
                )
                
                # Check for valid HTML response free of captchas / bot verification walls
                if resp.status_code == 200:
                    text_sample = resp.text[:4000].lower()
                    if not any(w in text_sample for w in ["bm-verify", "api-services-support", "validatecaptcha", "enter the characters"]):
                        return BeautifulSoup(resp.text, 'html.parser')
                
                # If challenged, apply exponential backoff with jitter
                backoff_wait = (1.2 * (1.8 ** attempt)) + random.uniform(0.3, 0.9)
                time.sleep(backoff_wait)
            except Exception:
                time.sleep(1.0 + attempt * 0.8)
        return None

    def extract_search_asins(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Extract all product cards from an Amazon search results page."""
        products = []
        items = soup.select('div[data-asin]:not([data-asin=""])')
        seen_page_asins = set()
        
        for item in items:
            asin = item.get('data-asin', '').strip()
            if not asin or len(asin) != 10 or asin in seen_page_asins:
                continue

            # Product Title
            title_node = item.select_one('h2')
            title = title_node.get_text(strip=True) if title_node else ""
            if not title:
                continue

            seen_page_asins.add(asin)

            # Price
            price_node = item.select_one('.a-price .a-offscreen, .a-price-whole')
            price = price_node.get_text(strip=True) if price_node else "N/A"

            # Rating
            rating_node = item.select_one('.a-icon-alt')
            rating = rating_node.get_text(strip=True) if rating_node else "N/A"

            # Reviews count
            reviews = 0
            for aria_node in item.select('span[aria-label*="rating"], span[aria-label*="review"], a[aria-label*="rating"], a[aria-label*="review"]'):
                lbl = aria_node.get('aria-label', '')
                if not re.search(r'out of|stars|von 5|sur 5|de 5', lbl, re.IGNORECASE):
                    m_lbl = re.search(r'([\d,]+)', lbl)
                    if m_lbl:
                        try:
                            reviews = int(m_lbl.group(1).replace(',', ''))
                            break
                        except Exception:
                            pass
            if reviews == 0:
                for sel in ['.s-underline-text', 'a[href*="#customerReviews"] span', 'a[href*="#customerReviews"]']:
                    rev_node = item.select_one(sel)
                    if rev_node:
                        txt = rev_node.get_text(strip=True).replace(',', '').replace('.', '')
                        if re.match(r'^\d+$', txt):
                            try:
                                reviews = int(txt)
                                break
                            except Exception:
                                pass

            # Card brand if displayed
            card_brand = ""
            brand_node = item.select_one('span.a-size-base-plus.a-color-base, [data-cy="title-recipe"] h2 ~ span, .s-line-clamp-1 span')
            if brand_node:
                b_cand = brand_node.get_text(strip=True)
                if len(b_cand) >= 2 and len(b_cand) < 40 and not any(w in b_cand.lower() for w in ['pack', 'count', 'ounce', 'star', 'rating', 'review', 'save', 'prime', 'choice', 'sponsored']):
                    card_brand = b_cand

            # Product URL
            link_node = item.select_one('h2 a[href]')
            rel_url = link_node.get('href', '') if link_node else f"/dp/{asin}"
            if rel_url.startswith('/'):
                product_url = f"{self.base_url}{rel_url}"
            else:
                product_url = rel_url

            products.append({
                "asin": asin,
                "title": title,
                "price": price,
                "rating": rating,
                "reviews": reviews,
                "brand": card_brand,
                "product_url": product_url
            })
            
        return products

    def inspect_asin_details(self, asin: str) -> Dict[str, Any]:
        """
        Deep-inspects an ASIN product page:
        - Extracts exact Brand Name
        - Checks for Amazon Brand Store link
        - Checks for A+ Content & Brand Story
        - Extracts Buy Box seller
        - Extracts other sellers & offer count
        """
        product_url = f"{self.base_url}/dp/{asin}"
        soup = self.fetch_page(product_url)
        if not soup:
            return {
                "brand": "",
                "buybox_seller": "",
                "all_sellers": [],
                "has_brand_store": False,
                "has_aplus": False,
                "total_offers": 1,
                "page_fetched": False
            }

        # 1. Extract Brand Name & Check Storefront
        brand = ""
        has_brand_store = False
        byline = soup.find(id='bylineInfo')
        if byline:
            b_text = byline.get_text(strip=True)
            href = byline.get('href', '')
            if '/stores/' in href or 'Visit the' in b_text:
                has_brand_store = True

            b_text = re.sub(r'^(Visit the|Brand:)\s*', '', b_text, flags=re.IGNORECASE)
            b_text = re.sub(r'\s+Store$', '', b_text, flags=re.IGNORECASE).strip()
            brand = b_text

        if not brand:
            po_brand = soup.select_one('.po-brand .po-break-word, tr.po-brand td span')
            if po_brand:
                brand = po_brand.get_text(strip=True)

        # 2. Check A+ Content & Brand Story
        has_aplus = False
        if soup.select_one('#aplus, .aplus-v2, #dpx-aplus-brand-story_feature_div, [data-feature-name="aplus"]'):
            has_aplus = True

        # 3. Extract Buy Box Seller (Multi-Strategy Parser)
        buybox_seller = ""
        seller_profile = soup.find(id='sellerProfileTriggerId')
        if seller_profile and seller_profile.get_text(strip=True):
            buybox_seller = seller_profile.get_text(strip=True)
        elif soup.find(id='merchant-info'):
            m_text = soup.find(id='merchant-info').get_text(strip=True)
            m = re.search(r'Sold by\s+([^,\.]+?)(?:\s+and\s+ships|\s*\(|\s*$|\.)', m_text, re.IGNORECASE)
            buybox_seller = m.group(1).strip() if m else m_text[:50].strip()
        else:
            # Check tabular-buybox and any elements with "Sold by"
            for node in soup.find_all(['span', 'div', 'td', 'p'], string=re.compile(r'Sold by', re.I)):
                txt = node.get_text(strip=True)
                m = re.search(r'Sold by\s+([^,\.]+?)(?:\s+and\s+ships|\s*\(|\s*$|\.)', txt, re.I)
                if m:
                    cand = m.group(1).strip()
                    if cand and len(cand) < 60 and not any(w in cand.lower() for w in ['amazon', 'return', 'refund', 'detail']):
                        buybox_seller = cand
                        break
                parent = node.parent
                if parent:
                    link = parent.find('a')
                    if link and link.get_text(strip=True):
                        cand = link.get_text(strip=True)
                        if len(cand) < 60 and not any(w in cand.lower() for w in ['amazon', 'return', 'detail']):
                            buybox_seller = cand
                            break

        # 4. Check Other Sellers & Total Offers count
        all_sellers = []
        if buybox_seller:
            all_sellers.append(buybox_seller)

        for a in soup.find_all('a', href=True):
            href = a['href']
            if any(k in href for k in ['/seller/at-a-glance.html', 'seller=', '/shops/']):
                s_name = a.get_text(strip=True)
                if s_name and len(s_name) < 50 and not any(w in s_name.lower() for w in ['help', 'return', 'details', 'policy', 'review']):
                    if s_name not in all_sellers:
                        all_sellers.append(s_name)

        # Detect total offers number (e.g., "New (12) from $...")
        total_offers = max(len(all_sellers), 1)
        olp_text = soup.select_one('#olpLinkWidget, #all-offers-display, #dynamic-aod-ingress-box')
        if olp_text:
            raw_olp = olp_text.get_text(strip=True)
            m_offers = re.search(r'New\s*\((\d+)\)', raw_olp, re.IGNORECASE)
            if m_offers:
                total_offers = max(total_offers, int(m_offers.group(1)))

        # Extract review count from product page
        page_reviews = 0
        rev_el = soup.select_one('#acrCustomerReviewText, [data-hook="total-review-count"], #acrCustomerReviewLink')
        if rev_el:
            rev_txt = rev_el.get_text(strip=True).replace(',', '')
            m_rev = re.search(r'(\d+)', rev_txt)
            if m_rev:
                try:
                    page_reviews = int(m_rev.group(1))
                except Exception:
                    pass

        return {
            "brand": brand.strip(),
            "buybox_seller": buybox_seller.strip(),
            "all_sellers": all_sellers,
            "has_brand_store": has_brand_store,
            "has_aplus": has_aplus,
            "total_offers": total_offers,
            "reviews": page_reviews,
            "page_fetched": True
        }

    def run_pipeline(
        self,
        query: str,
        max_pages: int = 10,
        max_reviews: Optional[int] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        should_stop_check: Optional[Callable[[], bool]] = None
    ) -> List[Dict[str, Any]]:
        """
        Fast Multi-Page Crawler (Pages 1 to 10):
        - Rapidly crawls up to max_pages
        - Negates wholesale, Amazon 1P, and enterprise brands
        - Verifies PL signals (A+, Storefront, Seller match)
        - Deduplicates brands across all pages
        - Discovers founders on LinkedIn
        """
        max_pages = max(1, min(max_pages, 10))
        extracted_records = []
        self.seen_brands: Set[str] = set()
        seen_asins: Set[str] = set()
        total_scanned_count = 0
        current_page_url = self.build_search_url(query, 1)

        for page in range(1, max_pages + 1):
            if should_stop_check and should_stop_check():
                break
            
            if progress_callback:
                progress_callback({
                    "status": "crawling_page",
                    "current_page": page,
                    "max_pages": max_pages,
                    "message": f"Crawling page {page} of {max_pages}...",
                    "total_found": len(extracted_records)
                })

            soup = self.fetch_page(current_page_url)
            if not soup:
                if progress_callback:
                    progress_callback({
                        "status": "warning",
                        "current_page": page,
                        "max_pages": max_pages,
                        "message": f"Amazon rate-limited automated search on page {page}. Tip: Use '⚡ Extract from Active Tab' for instant extraction!",
                        "total_found": len(extracted_records)
                    })
                time.sleep(2.0)
                current_page_url = self.build_search_url(query, page + 1)
                continue

            products = self.extract_search_asins(soup)
            if not products:
                # End of results
                break

            # Prepare native next page link from Amazon's DOM (includes valid qid & xpid tokens)
            next_a = soup.select_one('.s-pagination-next')
            if next_a and 's-pagination-disabled' not in next_a.get('class', []):
                next_href = next_a.get('href', '')
                if next_href:
                    current_page_url = f"{self.base_url}{next_href}" if next_href.startswith('/') else next_href
                else:
                    current_page_url = self.build_search_url(query, page + 1)
            else:
                current_page_url = self.build_search_url(query, page + 1)

            # Filter out products already scanned by ASIN, megabrands, or already extracted brands
            unseen_products = []
            for p in products:
                asin = p.get("asin")
                if not asin or asin in seen_asins:
                    continue
                seen_asins.add(asin)

                # Skip if already over max_reviews limit
                if max_reviews is not None and p.get("reviews", 0) >= max_reviews:
                    continue

                # Skip if known megabrand or brand already extracted
                c_brand = (p.get("brand") or "").lower().strip()
                if c_brand:
                    if c_brand in self.seen_brands or is_megabrand_or_corporate(c_brand):
                        continue

                unseen_products.append(p)

            # Analyze products concurrently in small fast batches (4 workers)
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_prod = {
                    executor.submit(self.inspect_asin_details, p["asin"]): p
                    for p in unseen_products
                }

                for future in as_completed(future_to_prod):
                    if should_stop_check and should_stop_check():
                        break

                    prod = future_to_prod[future]
                    total_scanned_count += 1
                    try:
                        details = future.result()
                    except Exception:
                        continue

                    brand_name = details.get("brand") or ""
                    if not brand_name or brand_name.lower() in ["unknown", "generic", "brand", "null", "none", "n/a", "unbranded"] or len(brand_name) < 2:
                        continue

                    norm_b = brand_name.lower().strip()
                    if norm_b in self.seen_brands:
                        continue

                    # Strict PL Evaluation with Negation
                    pl_eval = evaluate_private_label(
                        brand_name=brand_name,
                        buybox_seller=details.get("buybox_seller", ""),
                        all_sellers=details.get("all_sellers", []),
                        has_brand_store=details.get("has_brand_store", False),
                        has_aplus_content=details.get("has_aplus", False),
                        total_offers_count=details.get("total_offers", 1)
                    )

                    # Only accept verified Private Label
                    if pl_eval["is_private_label"]:
                        prod_reviews = details.get("reviews") or prod.get("reviews") or 0
                        if max_reviews is not None and prod_reviews >= max_reviews:
                            continue

                        self.seen_brands.add(norm_b)

                        if progress_callback:
                            progress_callback({
                                "status": "enriching_brand",
                                "current_page": page,
                                "max_pages": max_pages,
                                "total_scanned": total_scanned_count,
                                "brand_name": brand_name,
                                "asin": prod["asin"],
                                "message": f"[Page {page}/{max_pages}] Verified PL: '{brand_name}' ({prod_reviews} reviews). Searching LinkedIn...",
                                "total_found": len(extracted_records)
                            })

                        # Search decision maker
                        decision_maker = find_decision_maker(brand_name)

                        record = {
                            "asin": prod["asin"],
                            "brand_name": brand_name,
                            "founder_name": decision_maker.get("founder_name", "Not Found"),
                            "linkedin_url": decision_maker.get("linkedin_url", "Not Found"),
                            "decision_maker_role": decision_maker.get("role_title", ""),
                            "pl_confidence": pl_eval.get("confidence", "High"),
                            "matched_seller": pl_eval.get("matched_seller", ""),
                            "seller_match_type": pl_eval.get("seller_match_type", ""),
                            "buybox_seller": details.get("buybox_seller", "None"),
                            "all_sellers_found": ", ".join(details.get("all_sellers", [])) or details.get("buybox_seller", ""),
                            "product_title": prod.get("title", ""),
                            "price": prod.get("price", ""),
                            "rating": prod.get("rating", ""),
                            "reviews": prod_reviews,
                            "product_url": prod.get("product_url", f"{self.base_url}/dp/{prod['asin']}"),
                            "page": page
                        }

                        extracted_records.append(record)

                        if progress_callback:
                            progress_callback({
                                "status": "brand_added",
                                "current_page": page,
                                "max_pages": max_pages,
                                "total_scanned": total_scanned_count,
                                "record": record,
                                "total_found": len(extracted_records),
                                "message": f"Added PL Brand: {brand_name} (Page {page})"
                            })

            if progress_callback and page < max_pages:
                progress_callback({
                    "status": "page_completed",
                    "current_page": page,
                    "max_pages": max_pages,
                    "message": f"Finished page {page}/{max_pages}! Moving to page {page + 1}...",
                    "total_found": len(extracted_records)
                })

            time.sleep(self.delay)

        if progress_callback:
            progress_callback({
                "status": "completed",
                "total_scanned": total_scanned_count,
                "total_pl_brands": len(extracted_records),
                "message": f"Deep Search complete! Extracted {len(extracted_records)} verified Private Label brands across {page} pages."
            })

        return extracted_records
