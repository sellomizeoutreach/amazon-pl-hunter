import re
import urllib.parse
from typing import Dict, Any, Optional
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests
    HAS_CURL_CFFI = True
except Exception:
    import requests
    HAS_CURL_CFFI = False

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

# ============================================================================
# COMPREHENSIVE CHINESE SELLER IDENTIFICATION DATA (Provinces, Cities, Pinyin)
# ============================================================================

CHINESE_PROVINCES = {
    "guangdong", "guang dong", "canton", "kwangtung",
    "zhejiang", "zhe jiang", "chekiang",
    "fujian", "fu jian", "fukien",
    "jiangsu", "jiang su", "kiangsu",
    "shandong", "shan dong", "shantung",
    "henan", "he nan", "honan",
    "sichuan", "si chuan", "szechwan", "szechuan",
    "hunan", "hu nan",
    "hubei", "hu bei", "hupeh",
    "hebei", "he bei", "hopeh",
    "anhui", "an hui", "anhwei",
    "jiangxi", "jiang xi", "kiangsi",
    "shaanxi", "shaan xi", "shensi",
    "shanxi", "shan xi", "shansi",
    "liaoning", "liao ning",
    "jilin", "ji lin", "kirin",
    "heilongjiang", "hei long jiang", "heilungkiang",
    "guizhou", "gui zhou", "kweichow",
    "yunnan", "yun nan",
    "guangxi", "guang xi", "kwangsi",
    "hainan", "hai nan",
    "ningxia", "ning xia",
    "xinjiang", "xin jiang", "sinkiang",
    "qinghai", "qing hai", "tsinghai",
    "gansu", "gan su", "kansu",
    "inner mongolia", "neimenggu", "nei mongol",
    "tibet", "xizang",
    "beijing", "bei jing", "peking",
    "shanghai", "shang hai",
    "tianjin", "tian jin", "tientsin",
    "chongqing", "chong qing", "chungking",
}

CHINESE_CITIES = {
    # Guangdong
    "shenzhen", "guangzhou", "dongguan", "foshan", "huizhou", "zhongshan", "zhuhai",
    "shantou", "jiangmen", "jieyang", "chaozhou", "zhanjiang", "maoming", "zhaoqing",
    "meizhou", "shanwei", "heyuan", "yangjiang", "qingyuan", "shaoguan", "yunfu",
    # Zhejiang
    "hangzhou", "yiwu", "ningbo", "wenzhou", "jinhua", "shaoxing", "taizhou",
    "jiaxing", "huzhou", "quzhou", "zhoushan", "lishui", "yuyao", "cixi", "cangnan",
    # Fujian
    "xiamen", "fuzhou", "quanzhou", "putian", "zhangzhou", "nanping", "longyan",
    "sanming", "ningde", "jinjiang", "shishi", "dehua", "anxi",
    # Jiangsu
    "suzhou", "nanjing", "wuxi", "changzhou", "nantong", "yangzhou", "xuzhou",
    "yancheng", "zhenjiang", "huaian", "huai'an", "lianyungang", "suqian", "kunshan",
    "changshu", "zhangjiagang", "taicang", "jiangyin", "yixing",
    # Shandong
    "qingdao", "jinan", "yantai", "weihai", "weifang", "linyi", "zibo", "jining",
    "tai'an", "taian", "dezhou", "liaocheng", "binzhou", "heze", "rizhao", "dongying",
    # Henan
    "zhengzhou", "luoyang", "nanyang", "xinxiang", "anyang", "xuchang", "pingdingshan",
    "kaifeng", "jiaozuo", "shangqiu", "zhoukou", "zhumadian", "xinyang", "puyang",
    # Sichuan
    "chengdu", "mianyang", "deyang", "yibin", "nanchong", "luzhou", "leshan", "zigong",
    # Hubei
    "wuhan", "yichang", "xiangyang", "jingzhou", "huanggang", "xiaogan", "huangshi",
    # Hunan
    "changsha", "zhuzhou", "xiangtan", "hengyang", "yueyang", "changde", "chenzhou",
    # Shaanxi & Shanxi
    "xi'an", "xian", "baoji", "xianyang", "weinan", "hanzhong", "yulin", "taiyuan", "datong",
    # Hebei
    "shijiazhuang", "baoding", "tangshan", "cangzhou", "handan", "xingtai", "langfang",
    "qinhuangdao", "hengshui", "zhangjiakou", "chengde",
    # Anhui
    "hefei", "wuhu", "bengbu", "anqing", "fuyang", "chuzhou", "ma'anshan", "maanshan", "lu'an",
    # Jiangxi
    "nanchang", "ganzhou", "jiujiang", "shangrao", "yichun", "ji'an", "jian", "pingxiang", "jingdezhen",
    # Northeast
    "shenyang", "dalian", "anshan", "fushun", "harbin", "daqing", "qiqihar", "changchun", "jilin",
    # Southwest & Northwest
    "kunming", "guiyang", "nanning", "guilin", "haikou", "sanya", "hohhot", "urumqi", "yinchuan", "xining", "lanzhou"
}

CHINESE_DISTRICTS = {
    "baoan", "bao'an", "longgang", "futian", "nanshan", "luohu", "longhua", "guangming", "pingshan", "yantian",
    "tianhe", "baiyun", "yuexiu", "haizhu", "panyu", "huangpu", "huadu", "conghua", "zengcheng", "nansha",
    "choucheng", "beiyuan", "jiangdong", "choujiang", "fotang", "shangxi", "yiting",
    "binjiang", "xiaoshan", "yuhang", "xihu", "gongshu", "shangcheng",
    "siming", "huli", "jimei", "haicang", "tong'an", "tongan", "xiang'an", "xiangan",
    "wujin", "gusu", "wuzhong", "xiangcheng", "jiangning", "pukou", "qixia", "yuhuatai"
}

CHINESE_CORP_KEYWORDS = {
    "youxian gongsi", "youxiangongsi", "keji youxian", "maoyi youxian",
    "dianzi shangwu", "dianshang", "gongsi", "keji", "maoyi", "shiye",
    "youxian", "gongcheng", "zhizao", "fuzhuang", "piju", "xiangbao"
}

HONG_KONG_KEYWORDS = {
    "hong kong", "hongkong", "kowloon", "new territories", "mong kok",
    "tsim sha tsui", "wan chai", "central", "kwun tong", "sha tin", "tsuen wan", "admiralty"
}

def detect_seller_country(business_name: str, address_lines: list, full_text: str = "") -> Dict[str, str]:
    """
    Exhaustively detects the seller's true registered country, even when business names
    are in English or Amazon's address field omits explicit country codes.
    """
    b_name = (business_name or "").strip()
    addr_str = " ".join(address_lines or []).strip()
    full_sample = f"{b_name} {addr_str} {full_text}".lower()

    # 1. Check for Chinese Characters (Unicode range \u4e00-\u9fff)
    if re.search(r'[\u4e00-\u9fff]', full_sample):
        return {
            "country_code": "CN",
            "country_name": "China",
            "display": "🇨🇳 China",
            "detected_origin": "Chinese Characters Identified"
        }

    # 2. Check for explicit Hong Kong markers
    for hk_term in HONG_KONG_KEYWORDS:
        if re.search(rf'\b{re.escape(hk_term)}\b', full_sample):
            return {
                "country_code": "HK",
                "country_name": "Hong Kong",
                "display": "🇭🇰 Hong Kong",
                "detected_origin": f"Hong Kong ({hk_term.title()})"
            }

    # 3. Check for explicit China country markers
    if re.search(r'\b(cn|china|people\'s republic of china|prc|p\.r\. china|p\.r\.c\.)\b', full_sample):
        matched_city = None
        for c in CHINESE_CITIES:
            if re.search(rf'\b{re.escape(c)}\b', full_sample):
                matched_city = c.title()
                break
        matched_prov = None
        for p in CHINESE_PROVINCES:
            if re.search(rf'\b{re.escape(p)}\b', full_sample):
                matched_prov = p.title()
                break
        detail = f" ({matched_city or matched_prov})" if (matched_city or matched_prov) else ""
        return {
            "country_code": "CN",
            "country_name": "China",
            "display": f"🇨🇳 China{detail}",
            "detected_origin": f"China {matched_prov or ''} {matched_city or ''}".strip()
        }

    # 4. Check for Chinese Provinces (in business name, address lines, or full text)
    for prov in CHINESE_PROVINCES:
        if re.search(rf'\b{re.escape(prov)}\b', full_sample):
            matched_city = None
            for c in CHINESE_CITIES:
                if re.search(rf'\b{re.escape(c)}\b', full_sample):
                    matched_city = c.title()
                    break
            detail = f" ({matched_city or prov.title()})"
            return {
                "country_code": "CN",
                "country_name": "China",
                "display": f"🇨🇳 China{detail}",
                "detected_origin": f"Guaranteed CN ({prov.title()})"
            }

    # 5. Check for Chinese Cities (in business name or address)
    for city in CHINESE_CITIES:
        if re.search(rf'\b{re.escape(city)}\b', full_sample):
            return {
                "country_code": "CN",
                "country_name": "China",
                "display": f"🇨🇳 China ({city.title()})",
                "detected_origin": f"Guaranteed CN ({city.title()})"
            }

    # 6. Check for Pinyin City/Province suffix patterns: e.g. "shenzhenshi", "guangdongsheng"
    pinyin_suffix_match = re.search(r'\b([a-z]{3,15})(shi|sheng)\b', full_sample)
    if pinyin_suffix_match:
        stem = pinyin_suffix_match.group(1).title()
        return {
            "country_code": "CN",
            "country_name": "China",
            "display": f"🇨🇳 China ({stem})",
            "detected_origin": f"Pinyin Admin Division ({stem})"
        }

    # 7. Check for Chinese district tokens: e.g. "Baoan Qu", "Longgang", "Tianhe", "Choucheng"
    for dist in CHINESE_DISTRICTS:
        if re.search(rf'\b{re.escape(dist)}\b', full_sample):
            return {
                "country_code": "CN",
                "country_name": "China",
                "display": f"🇨🇳 China ({dist.title()})",
                "detected_origin": f"Chinese District ({dist.title()})"
            }

    # 8. Check for Chinese corporate keywords: e.g. "youxian gongsi", "keji", "maoyi"
    for corp_kw in CHINESE_CORP_KEYWORDS:
        if re.search(rf'\b{re.escape(corp_kw)}\b', full_sample):
            return {
                "country_code": "CN",
                "country_name": "China",
                "display": "🇨🇳 China",
                "detected_origin": f"Chinese Entity Naming ({corp_kw})"
            }

    # 9. Check for Chinese 6-digit postal code pattern (e.g. 518000, 310000, 322000, 510000)
    for line in address_lines:
        line_clean = line.strip().upper()
        if re.search(r'\b[1-8]\d{5}\b', line_clean):
            if not any(us_state in line_clean for us_state in [" US", " USA", "UNITED STATES"]):
                return {
                    "country_code": "CN",
                    "country_name": "China",
                    "display": "🇨🇳 China",
                    "detected_origin": "Chinese Postal Code"
                }

    # 10. Check other countries
    raw_country = address_lines[-1].strip().upper() if address_lines else "Unknown"

    if re.search(r'\b(united states|usa|u\.s\.a\.|u\.s\.|us)\b', raw_country.lower()) or raw_country in ["US", "USA"]:
        return {"country_code": "US", "country_name": "United States", "display": "🇺🇸 United States", "detected_origin": "US"}
    elif re.search(r'\b(united kingdom|great britain|england|scotland|wales|uk|gb)\b', raw_country.lower()) or raw_country in ["GB", "UK"]:
        return {"country_code": "GB", "country_name": "United Kingdom", "display": "🇬🇧 United Kingdom", "detected_origin": "GB"}
    elif re.search(r'\b(germany|deutschland|de)\b', raw_country.lower()) or raw_country == "DE":
        return {"country_code": "DE", "country_name": "Germany", "display": "🇩🇪 Germany", "detected_origin": "DE"}
    elif re.search(r'\b(canada|ca)\b', raw_country.lower()) or raw_country == "CA":
        return {"country_code": "CA", "country_name": "Canada", "display": "🇨🇦 Canada", "detected_origin": "CA"}
    elif re.search(r'\b(france|fr)\b', raw_country.lower()) or raw_country == "FR":
        return {"country_code": "FR", "country_name": "France", "display": "🇫🇷 France", "detected_origin": "FR"}
    elif re.search(r'\b(italy|italia|it)\b', raw_country.lower()) or raw_country == "IT":
        return {"country_code": "IT", "country_name": "Italy", "display": "🇮🇹 Italy", "detected_origin": "IT"}
    elif re.search(r'\b(spain|espana|es)\b', raw_country.lower()) or raw_country == "ES":
        return {"country_code": "ES", "country_name": "Spain", "display": "🇪🇸 Spain", "detected_origin": "ES"}
    elif re.search(r'\b(australia|au)\b', raw_country.lower()) or raw_country == "AU":
        return {"country_code": "AU", "country_name": "Australia", "display": "🇦🇺 Australia", "detected_origin": "AU"}
    elif re.search(r'\b(india|in)\b', raw_country.lower()) or raw_country == "IN":
        return {"country_code": "IN", "country_name": "India", "display": "🇮🇳 India", "detected_origin": "IN"}
    elif re.search(r'\b(japan|jp)\b', raw_country.lower()) or raw_country == "JP":
        return {"country_code": "JP", "country_name": "Japan", "display": "🇯🇵 Japan", "detected_origin": "JP"}
    elif len(raw_country) == 2 and raw_country.isalpha():
        c_name = COUNTRY_NAMES.get(raw_country, raw_country)
        c_flag = COUNTRY_FLAGS.get(raw_country, raw_country)
        return {"country_code": raw_country, "country_name": c_name, "display": f"{c_flag} ({c_name})", "detected_origin": raw_country}

    # Address-wide check for United States
    if re.search(r'\b(united states|usa)\b', addr_str.lower()):
        return {"country_code": "US", "country_name": "United States", "display": "🇺🇸 United States", "detected_origin": "US Address"}

    return {
        "country_code": "Unknown",
        "country_name": "Unknown",
        "display": "Unknown",
        "detected_origin": "Not Available"
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
        headers = {"Accept-Language": "en-US,en;q=0.9"}
        if HAS_CURL_CFFI:
            resp = requests.get(
                url,
                impersonate="chrome124",
                headers=headers,
                cookies=req_cookies,
                timeout=8
            )
        else:
            headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            resp = requests.get(
                url,
                headers=headers,
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

        full_text = soup.get_text(separator=' ', strip=True)

        # Deep multi-layer country & Chinese origin detection
        detected_info = detect_seller_country(business_name, address_lines, full_text=full_text)
        country_code = detected_info["country_code"]
        country_name = detected_info["country_name"]
        display_str = detected_info["display"]

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

EXCLUDE_COUNTRY_CHOICES = {
    "🇨🇳 China (CN)": "CN",
    "🇭🇰 Hong Kong (HK)": "HK",
    "🇺🇸 United States (US)": "US",
    "🇬🇧 United Kingdom (GB)": "GB",
    "🇩🇪 Germany (DE)": "DE",
    "🇨🇦 Canada (CA)": "CA",
    "🇫🇷 France (FR)": "FR",
    "🇮🇹 Italy (IT)": "IT",
    "🇪🇸 Spain (ES)": "ES",
    "🇮🇳 India (IN)": "IN",
    "🇯🇵 Japan (JP)": "JP",
    "🇦🇺 Australia (AU)": "AU",
    "❓ Unknown Country": "UNKNOWN"
}

def is_seller_allowed(
    seller_country: str,
    region_filter: Optional[str] = None,
    exclude_countries: Optional[Any] = None
) -> bool:
    """
    Checks if a seller's registered country is allowed based on:
    1. exclude_countries: List or comma-separated string of country codes to reject/skip.
    2. region_filter: Required region code or whitelist group.
    """
    c = (seller_country or "UNKNOWN").upper().strip()

    if exclude_countries:
        exclude_set = set()
        if isinstance(exclude_countries, str):
            raw_items = [x.strip().upper() for x in exclude_countries.split(",") if x.strip()]
        elif isinstance(exclude_countries, (list, tuple, set)):
            raw_items = [str(x).strip().upper() for x in exclude_countries if str(x).strip()]
        else:
            raw_items = []

        for item in raw_items:
            if item in ["CN_HK", "CHINA_HK", "CHINA"]:
                exclude_set.add("CN")
                exclude_set.add("HK")
            elif item in ["UK_EU", "EU"]:
                exclude_set.update(["GB", "UK", "DE", "FR", "IT", "ES", "NL", "PL", "SE", "IE"])
            elif item in EXCLUDE_COUNTRY_CHOICES.values():
                exclude_set.add(item)
            elif item in EXCLUDE_COUNTRY_CHOICES:
                exclude_set.add(EXCLUDE_COUNTRY_CHOICES[item])
            else:
                exclude_set.add(item)

        if c in exclude_set:
            return False

    return matches_region_filter(seller_country, region_filter)

def matches_region_filter(seller_country: str, region_filter: Optional[str], exclude_countries: Optional[Any] = None) -> bool:
    """
    Checks if a seller's registered country matches the requested region filter:
    - 'ALL' or None: Matches everything
    - 'US': United States only
    - 'NON_CN': Non-China (all sellers NOT in CN/HK)
    - 'CN': China & Hong Kong (CN, HK)
    - 'UK_EU': United Kingdom & Europe (GB, UK, DE, FR, IT, ES, NL, PL, SE)
    - 'CA': Canada
    """
    if exclude_countries:
        if not is_seller_allowed(seller_country, region_filter=None, exclude_countries=exclude_countries):
            return False

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

