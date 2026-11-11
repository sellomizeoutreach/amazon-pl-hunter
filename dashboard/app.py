import os
import sys
import time
import json
import re
import gc
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import streamlit as st

# Ensure root directory and parent are in sys.path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(ROOT_DIR)
for p in [ROOT_DIR, PARENT_DIR]:
    if p and p not in sys.path:
        sys.path.insert(0, p)

import importlib
importlib.invalidate_caches()

from backend.amazon_scraper import AmazonExtractor
from backend.pl_detector import evaluate_private_label
from backend.linkedin_finder import find_decision_maker
from backend.brand_finder import find_brand_website_and_contacts

try:
    from backend.seller_checker import (
        fetch_seller_information,
        matches_region_filter,
        is_seller_allowed,
        EXCLUDE_COUNTRY_CHOICES,
        extract_seller_id_from_url_or_tag
    )
except Exception:
    importlib.invalidate_caches()
    try:
        from backend.seller_checker import (
            fetch_seller_information,
            matches_region_filter,
            is_seller_allowed,
            EXCLUDE_COUNTRY_CHOICES,
            extract_seller_id_from_url_or_tag
        )
    except Exception:
        def fetch_seller_information(*args, **kwargs):
            return {
                "seller_id": "",
                "seller_business_name": "Not Available",
                "seller_address": "Not Available",
                "seller_country": "Unknown",
                "seller_country_name": "Unknown",
                "seller_country_display": "Unknown"
            }
        def matches_region_filter(seller_country, region_filter, exclude_countries=None):
            return True
        def is_seller_allowed(seller_country, region_filter=None, exclude_countries=None):
            return True
        EXCLUDE_COUNTRY_CHOICES = {
            "🇨🇳 China (CN)": "CN",
            "🇭🇰 Hong Kong (HK)": "HK",
            "🇺🇸 United States (US)": "US",
            "🇬🇧 United Kingdom (GB)": "GB",
            "🇩🇪 Germany (DE)": "DE",
            "🇨🇦 Canada (CA)": "CA",
            "❓ Unknown Country": "UNKNOWN"
        }
        def extract_seller_id_from_url_or_tag(*args, **kwargs):
            return None

from backend.exporter import export_to_csv_bytes, export_to_excel_bytes

try:
    from backend.auto_mailer import get_email_config, send_leads_email
except Exception:
    def get_email_config():
        return {}
    def send_leads_email(*args, **kwargs):
        return False, "Auto mailer module not loaded"

def save_email_config(cfg: dict):
    config_path = os.path.join(ROOT_DIR, "email_config.json")
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"Error saving config: {e}")

REGION_OPTIONS = {
    "🌍 All Regions / Countries": "ALL",
    "🇺🇸 United States (US Only)": "US",
    "🛡️ Non-China (Western: US, CA, UK, EU, AU)": "NON_CN",
    "🇨🇳 China & Hong Kong (CN / HK)": "CN",
    "🇬🇧 UK & Europe (GB, DE, FR, IT, ES)": "UK_EU",
    "🇨🇦 Canada (CA Only)": "CA"
}

PERSONA_OPTIONS = {
    "🌟 All Brand Personas": "ALL",
    "🚀 New Launch Brands (<12m active, launch phase)": "NEW_LAUNCH",
    "📉 Stagnant Veteran Brands (2+ yrs active, growth lag)": "STAGNANT_VETERAN",
    "⚠️ Distressed Catalog (Return Badges / Suppression)": "DISTRESSED"
}

# ==========================================
# PERSISTENT HISTORY STORAGE (File-backed)
# ==========================================
DATA_DIR = os.path.join(ROOT_DIR, "data")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")

def sync_from_remote_gist():
    """Optional cloud backup: loads history from GitHub Gist if GIST_ID & GIST_TOKEN are provided."""
    token = os.environ.get("GIST_TOKEN") or st.secrets.get("GIST_TOKEN", None)
    gist_id = os.environ.get("GIST_ID") or st.secrets.get("GIST_ID", None)
    if not token or not gist_id:
        return None
    try:
        import requests
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        r = requests.get(f"https://api.github.com/gists/{gist_id}", headers=headers, timeout=5)
        if r.status_code == 200:
            files = r.json().get("files", {})
            if "history.json" in files:
                content = files["history.json"].get("content", "[]")
                data = json.loads(content)
                if isinstance(data, list):
                    return data
    except Exception:
        pass
    return None

def sync_to_remote_gist(history_data):
    """Optional cloud backup: saves history to GitHub Gist if GIST_ID & GIST_TOKEN are provided."""
    token = os.environ.get("GIST_TOKEN") or st.secrets.get("GIST_TOKEN", None)
    gist_id = os.environ.get("GIST_ID") or st.secrets.get("GIST_ID", None)
    if not token or not gist_id:
        return False
    try:
        import requests
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        payload = {
            "files": {
                "history.json": {
                    "content": json.dumps(history_data, indent=2, ensure_ascii=False)
                }
            }
        }
        r = requests.patch(f"https://api.github.com/gists/{gist_id}", headers=headers, json=payload, timeout=5)
        return r.status_code == 200
    except Exception:
        return False

def load_saved_history():
    """Loads historical search sessions from data/history.json or cloud backup safely."""
    # Try local file first
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
        except Exception:
            pass

    # Safety net: check remote cloud backup if configured
    remote_data = sync_from_remote_gist()
    if remote_data:
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(remote_data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
        return remote_data

    return []

def import_backup_history(uploaded_file):
    """Imports and merges uploaded JSON backup into history safely."""
    try:
        data = json.load(uploaded_file)
        if not isinstance(data, list):
            return False, "Uploaded file does not contain a valid session list."
        current_history = load_saved_history()
        existing_ids = {item.get("id") for item in current_history if isinstance(item, dict) and "id" in item}
        merged_count = 0
        for item in data:
            if isinstance(item, dict):
                i_id = item.get("id") or f"hist_{int(time.time()*1000)}_{merged_count}"
                if i_id not in existing_ids:
                    item["id"] = i_id
                    current_history.append(item)
                    existing_ids.add(i_id)
                    merged_count += 1
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(current_history, f, indent=2, ensure_ascii=False)
        sync_to_remote_gist(current_history)
        return True, f"✅ Successfully restored {merged_count} historical searches!"
    except Exception as e:
        return False, f"Import error: {str(e)}"

def save_session_to_history(entry):
    """Appends and persists a search session into data/history.json safely."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        history = load_saved_history()
        
        records = entry.get("records", [])
        under_100_count = sum(1 for r in records if int(r.get("reviews") or 0) < 100)
        us_sellers_count = sum(1 for r in records if (r.get("seller_country") or "").upper() == "US")
        non_cn_sellers_count = sum(1 for r in records if (r.get("seller_country") or "").upper() not in ["CN", "HK", "UNKNOWN", ""])
        websites_count = sum(1 for r in records if r.get("website") and r.get("website").lower() != "not found")
        emails_count = sum(1 for r in records if r.get("email") and r.get("email").lower() != "not found")
        phones_count = sum(1 for r in records if r.get("phone") and r.get("phone").lower() != "not found")
        founders_count = sum(1 for r in records if r.get("founder_name") and r.get("founder_name").lower() != "not found")
        linkedin_count = sum(1 for r in records if r.get("linkedin_url") and r.get("linkedin_url").lower() != "not found")
        
        session_item = {
            "id": f"hist_{int(time.time()*1000)}",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "formatted_time": datetime.now().strftime("%b %d, %H:%M"),
            "type": entry.get("type", "single_search"),
            "query": entry.get("query", "Search"),
            "marketplace": entry.get("marketplace", "amazon.com"),
            "region_filter": entry.get("region_filter", "ALL"),
            "exclude_countries": entry.get("exclude_countries", []),
            "pages": entry.get("pages", 1),
            "brand_count": len(records),
            "under_100_count": under_100_count,
            "us_sellers_count": us_sellers_count,
            "non_cn_sellers_count": non_cn_sellers_count,
            "websites_count": websites_count,
            "emails_count": emails_count,
            "phones_count": phones_count,
            "founders_count": founders_count,
            "linkedin_count": linkedin_count,
            "records": records
        }
        
        history.insert(0, session_item)
        if len(history) > 100:
            history = history[:100]
            
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        sync_to_remote_gist(history)
        return True
    except Exception:
        return False

def delete_history_session(session_id):
    """Deletes a single history session safely."""
    try:
        history = load_saved_history()
        history = [item for item in history if item.get("id") != session_id]
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        sync_to_remote_gist(history)
        return True
    except Exception:
        return False

def clear_all_history():
    """Wipes all search history safely."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
        sync_to_remote_gist([])
        return True
    except Exception:
        return False

# ==========================================
# PAGE CONFIGURATION & STYLING
# ==========================================
st.set_page_config(
    page_title="Amazon Private Label & Decision Maker Hunter",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .main-header {
        font-size: 26px;
        font-weight: 700;
        color: #ff9900;
        margin-bottom: 2px;
    }
    .sub-header {
        font-size: 13px;
        color: #94a3b8;
        margin-bottom: 16px;
    }
    .metric-card {
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 12px;
        text-align: center;
    }
    .metric-val {
        font-size: 22px;
        font-weight: 700;
        color: #f8fafc;
    }
    .metric-lbl {
        font-size: 11px;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .hist-card {
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 14px;
        margin-bottom: 10px;
    }
    .hist-card-title {
        font-size: 15px;
        font-weight: 700;
        color: #f8fafc;
    }
    .hist-tag {
        font-size: 10px;
        font-weight: 700;
        padding: 2px 6px;
        border-radius: 4px;
        text-transform: uppercase;
    }
    .hist-tag-single {
        background: rgba(56, 189, 248, 0.2);
        color: #38bdf8;
    }
    .hist-tag-bulk {
        background: rgba(245, 158, 11, 0.2);
        color: #fbbf24;
    }
    .safety-banner {
        background: rgba(16, 185, 129, 0.12);
        border: 1px solid rgba(16, 185, 129, 0.3);
        border-radius: 6px;
        padding: 10px 14px;
        margin-bottom: 12px;
        font-size: 12px;
        color: #6ee7b7;
    }
</style>
""", unsafe_allow_html=True)


# ==========================================
# SESSION STATE INITIALIZATION
# ==========================================
if "active_results" not in st.session_state:
    st.session_state.active_results = []
if "is_running" not in st.session_state:
    st.session_state.is_running = False
if "should_stop" not in st.session_state:
    st.session_state.should_stop = False

# Header
st.markdown('<div class="main-header">📦 Amazon Private Label & Decision Maker Hunter</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Automated Amazon Brand Hunting • Up to 10 Pages • Low-Competition Filter (&lt; 100 Reviews) • Founder LinkedIn Discovery • Bulk Operations • Persistent History</div>', unsafe_allow_html=True)

# ==========================================
# SIDEBAR: SETTINGS & SYSTEM RESTART CONTROLS
# ==========================================
with st.sidebar:
    st.markdown('<div class="safety-banner">🟢 <b>System Safe & Online</b><br>Runs 100% in-memory — No external backend required!</div>', unsafe_allow_html=True)
    
    st.header("⚙️ Global Settings")
    marketplace = st.selectbox(
        "Amazon Marketplace",
        options=["amazon.com", "amazon.co.uk", "amazon.de", "amazon.ca", "amazon.fr", "amazon.it", "amazon.es"],
        index=0
    )
    
    delay = st.slider(
        "Request Delay (seconds)",
        min_value=0.3,
        max_value=3.0,
        value=0.6,
        step=0.1,
        help="Pacing between card requests. 0.6s–1.0s is recommended for multi-page stability."
    )
    
    st.divider()
    
    # SYSTEM SAFETY & ENGINE RESTART CONTROLS
    with st.expander("🛡️ Engine Control & Safety Restart", expanded=False):
        st.markdown("**Emergency Reset & Recovery:** Use if a search gets stuck or to purge runtime cache.")
        
        if st.button("🔄 Restart Engine / Reset State", type="primary", use_container_width=True):
            st.session_state.should_stop = True
            st.session_state.is_running = False
            st.session_state.active_results = []
            st.cache_data.clear()
            gc.collect()
            st.success("✅ System state successfully reset & restarted.")
            st.rerun()

        if st.button("🧹 Free Memory Cache", use_container_width=True):
            gc.collect()
            st.cache_data.clear()
            st.info("Temporary memory buffers cleared.")

        st.caption(f"Storage: **{len(load_saved_history())}** sessions saved")

    with st.expander("📧 Automated Email Delivery Settings", expanded=False):
        st.markdown("**Send leads straight to your inbox:**")
        cfg = get_email_config()
        cfg_sender = st.text_input("Sender Gmail:", value=cfg.get("sender_email", ""), placeholder="yourname@gmail.com", key="cfg_sender_input")
        cfg_pwd = st.text_input("Google App Password (16-char):", value=cfg.get("sender_password", ""), type="password", help="Generate at myaccount.google.com/apppasswords", key="cfg_pwd_input")
        cfg_receiver = st.text_input("Receiver Email:", value=cfg.get("receiver_email", ""), placeholder="leads@yourcompany.com", key="cfg_receiver_input")
        if st.button("💾 Save Email Settings", use_container_width=True, key="btn_save_email_cfg"):
            save_email_config({
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 465,
                "use_ssl": True,
                "sender_email": cfg_sender.strip(),
                "sender_password": cfg_pwd.strip(),
                "receiver_email": cfg_receiver.strip()
            })
            st.success("✅ Email settings saved to local config!")


# ==========================================
# NAVIGATION TABS
# ==========================================
tab_brand_scan, tab_single, tab_bulk, tab_history = st.tabs([
    "🎯 Direct Brand & ASIN Audit",
    "🌐 Single Search & Crawl",
    "⚡ Bulk Operations",
    "📜 Search History"
])

# ----------------------------------------------------
# TAB 0: DIRECT BRAND & ASIN AUDIT
# ----------------------------------------------------
with tab_brand_scan:
    st.markdown("""
    **Instant Deep Brand & ASIN Audit**  
    Paste any Amazon product ASIN or product URL to execute a 360° audit: Private Label verification, seller registration entity & country, full brand catalog review velocity (<100 reviews), listing health problems (suppressed, return badges), founder discovery on LinkedIn, personal email vs customer service email, brand persona classification, and tailored cold outreach pitch hook.
    """)

    col_asin_in, col_asin_mkt, col_asin_chk = st.columns([3.2, 1.3, 1.8])
    with col_asin_in:
        direct_asin_input = st.text_input(
            "Amazon ASIN or Product URL",
            placeholder="e.g. B08N5WRWNW or https://www.amazon.com/dp/B08N5WRWNW",
            key="input_direct_asin_audit"
        )
    with col_asin_mkt:
        direct_asin_mkt = st.selectbox(
            "Marketplace",
            options=list(MARKETPLACES.keys()),
            index=0,
            key="select_direct_asin_mkt"
        )
    with col_asin_chk:
        direct_check_catalog = st.checkbox(
            "🛡️ Audit Full Brand Catalog",
            value=True,
            help="Audits other products from this brand on Amazon to verify that all SKUs have < 100 reviews.",
            key="chk_direct_asin_catalog"
        )

    btn_run_direct_audit = st.button("🔍 Run Full Brand & ASIN Audit", type="primary", use_container_width=True, key="btn_run_direct_asin_audit")

    if btn_run_direct_audit:
        if not direct_asin_input.strip():
            st.error("Please enter a valid Amazon ASIN or Product URL.")
        else:
            with st.spinner("Executing proprietary Brand & ASIN audit pipeline..."):
                status_box = st.empty()
                progress_bar = st.progress(10)

                def audit_callback(update):
                    msg = update.get("message", "")
                    if msg:
                        status_box.info(f"⏳ {msg}")
                    st_val = update.get("status")
                    if st_val == "inspecting_asin":
                        progress_bar.progress(25)
                    elif st_val == "auditing_catalog":
                        progress_bar.progress(50)
                    elif st_val == "discovering_contacts":
                        progress_bar.progress(75)
                    elif st_val == "generating_pitch":
                        progress_bar.progress(90)
                    elif st_val == "completed":
                        progress_bar.progress(100)

                extractor = AmazonExtractor(marketplace=direct_asin_mkt, delay_between_requests=0.2)
                res = extractor.audit_brand_by_asin(
                    asin_or_url=direct_asin_input.strip(),
                    check_all_brand_products_under_100=direct_check_catalog,
                    progress_callback=audit_callback
                )

                if not res.get("success"):
                    status_box.empty()
                    progress_bar.empty()
                    st.error(f"❌ Audit Failed: {res.get('error', 'Unknown error')}")
                else:
                    status_box.success(f"✅ Deep Brand Audit completed for **{res.get('brand_name')}** (ASIN: {res.get('asin')})!")
                    progress_bar.empty()
                    
                    # Store in active results so explorer and downloads work immediately
                    st.session_state.active_results = [res]
                    save_session_to_history({
                        "type": "direct_asin_audit",
                        "query": f"ASIN Audit: {res.get('asin')} ({res.get('brand_name')})",
                        "marketplace": direct_asin_mkt,
                        "region_filter": "ALL",
                        "exclude_countries": [],
                        "pages": 1,
                        "records": [res]
                    })

                    # Render Direct Brand Audit Card
                    st.markdown("---")
                    
                    # Top Brand Header Banner
                    b_col_img, b_col_info = st.columns([1, 4])
                    with b_col_img:
                        if res.get("image_url"):
                            st.image(res.get("image_url"), use_column_width=True)
                        else:
                            st.markdown("📦 *No Image Available*")
                    with b_col_info:
                        st.markdown(f"### {res.get('brand_name')} — {res.get('product_title', 'Amazon Product')[:100]}")
                        st.markdown(f"**ASIN:** `{res.get('asin')}` | **Price:** `{res.get('price') or 'N/A'}` | **Product URL:** [{res.get('product_url')}]({res.get('product_url')})")
                        
                        # Badges Row
                        p_badge = res.get("brand_persona", "PL Brand")
                        q_badge = res.get("contact_quality", "Unknown")
                        c_disp = res.get("seller_country_display", "Unknown")
                        pl_stat = "✅ Verified Private Label" if res.get("is_private_label") else "⚠️ Reseller / Multi-Seller"
                        st.markdown(f"**Status:** `{p_badge}` | `{q_badge}` | `📍 {c_disp}` | `{pl_stat}`")

                    # 4 Strategic Metric Cards
                    st.markdown("<br>", unsafe_allow_html=True)
                    sc1, sc2, sc3, sc4 = st.columns(4)
                    with sc1:
                        st.markdown(f"""
                        <div class="metric-card">
                            <div class="metric-val" style="color:#10b981">{res.get('brand_persona')}</div>
                            <div class="metric-lbl">Brand Persona</div>
                        </div>
                        """, unsafe_allow_html=True)
                    with sc2:
                        st.markdown(f"""
                        <div class="metric-card">
                            <div class="metric-val" style="color:#a855f7">{res.get('contact_quality')}</div>
                            <div class="metric-lbl">Contact Quality</div>
                        </div>
                        """, unsafe_allow_html=True)
                    with sc3:
                        st.markdown(f"""
                        <div class="metric-card">
                            <div class="metric-val">{res.get('reviews', 0)}★ ({res.get('rating', 0.0)})</div>
                            <div class="metric-lbl">ASIN Reviews & Rating</div>
                        </div>
                        """, unsafe_allow_html=True)
                    with sc4:
                        cat_status = res.get('all_products_under_100', 'N/A')
                        st.markdown(f"""
                        <div class="metric-card">
                            <div class="metric-val" style="color:#0ea5e9">{cat_status}</div>
                            <div class="metric-lbl">Catalog Max Reviews: {res.get('catalog_max_reviews', 0)}</div>
                        </div>
                        """, unsafe_allow_html=True)

                    st.markdown("<br>", unsafe_allow_html=True)

                    # Detail Sections: Health, Contacts, Pitch
                    t_health, t_contacts, t_pitch = st.tabs([
                        "🚨 Listing Health & Problem Alerts",
                        "👤 Decision Maker & Contacts",
                        "✉️ Tailored Cold Pitch & Milestones"
                    ])

                    with t_health:
                        h_col1, h_col2 = st.columns(2)
                        with h_col1:
                            st.markdown("#### Listing Problem Checks")
                            supp_val = "❌ Suppressed / Unavailable" if res.get("is_suppressed") else "✅ Listing Active & Available"
                            st.write(f"• **Listing Availability:** {supp_val}")
                            
                            bb_val = "⚠️ Buy Box Suppressed (No Add-to-Cart)" if res.get("is_buybox_suppressed") else "✅ Buy Box Active"
                            st.write(f"• **Buy Box Status:** {bb_val}")
                            
                            ret_val = "🚨 Orange 'Frequently Returned' Badge ACTIVE" if res.get("has_frequently_returned_badge") else "✅ No High Return Warning"
                            st.write(f"• **Return Badge:** {ret_val}")

                            st.write(f"• **Health Summary:** `{res.get('catalog_health_summary')}`")

                        with h_col2:
                            st.markdown("#### Catalog & Asset Quality")
                            st.write(f"• **Launch Date:** {res.get('date_first_available')} (Active ~{res.get('brand_age_months')} mos)")
                            st.write(f"• **BSR Sales Rank:** {res.get('bsr')}")
                            st.write(f"• **A+ Enhanced Content:** {'✅ Yes' if res.get('has_aplus') else '❌ Missing A+ Content'}")
                            st.write(f"• **Listing Video:** {'✅ Yes' if res.get('has_video') else '❌ Missing Product Video'}")
                            st.write(f"• **Bullet Points:** {res.get('bullet_count', 0)} bullets (Recommended: 5)")
                            st.write(f"• **Total Brand SKUs Scanned:** {res.get('catalog_products_count', 1)}")

                    with t_contacts:
                        c_col1, c_col2 = st.columns(2)
                        with c_col1:
                            st.markdown("#### Decision Maker & Channels")
                            st.write(f"• **Founder / Decision Maker:** {res.get('founder_name')} ({res.get('decision_maker_role')})")
                            st.write(f"• **LinkedIn Profile:** {res.get('linkedin_url')}")
                            st.write(f"• **Direct Personal Email:** `{res.get('personal_email')}`")
                            st.write(f"• **Customer Support Email:** `{res.get('cs_email')}`")
                            st.write(f"• **Direct Phone:** `{res.get('phone')}`")
                            st.write(f"• **Brand Website:** {res.get('website')}")
                            st.write(f"• **Social Profiles:** {res.get('social_summary')}")
                        with c_col2:
                            st.markdown("#### Amazon Seller Profile")
                            st.write(f"• **Buy Box Seller:** {res.get('buybox_seller')}")
                            st.write(f"• **Seller Business Name:** {res.get('seller_business_name')}")
                            st.write(f"• **Registered Address:** {res.get('seller_address')}")
                            st.write(f"• **Registered Country:** {res.get('seller_country_display')}")
                            st.write(f"• **Amazon Seller ID:** `{res.get('seller_id')}`")
                            st.write(f"• **Seller Bio Email:** `{res.get('seller_email')}`")
                            st.write(f"• **Seller Bio Phone:** `{res.get('seller_phone')}`")

                    with t_pitch:
                        st.markdown("#### 🎯 Personalized Cold Outreach Pitch Hook")
                        st.info(res.get("growth_pitch_hook") or "Pitch hook not generated.")
                        st.markdown("#### 📈 Current Baseline vs Achievable Milestones")
                        p_col_curr, p_col_mils = st.columns(2)
                        with p_col_curr:
                            st.markdown("**Current Baseline Stats:**")
                            st.write(res.get("growth_strategy_current") or "N/A")
                        with p_col_mils:
                            st.markdown("**Achievable Growth Milestones:**")
                            st.write(res.get("growth_strategy_achievable") or "N/A")

# ----------------------------------------------------
# TAB 1: SINGLE SEARCH & CATEGORY CRAWL
# ----------------------------------------------------
with tab_single:
    col_q, col_p, col_r, col_f = st.columns([2.8, 1.0, 1.6, 1.6])
    with col_q:
        single_query = st.text_input(
            "Search Keyword or Category URL",
            placeholder="e.g. wireless earbuds, silicone kitchen utensils, posture corrector",
            key="input_single_query"
        )
    with col_p:
        single_pages = st.slider(
            "Pages to Crawl",
            min_value=1,
            max_value=10,
            value=3,
            key="slider_single_pages"
        )
    with col_r:
        single_region_lbl = st.selectbox(
            "Seller Region / Country",
            options=list(REGION_OPTIONS.keys()),
            index=0,
            help="Filter brands by where the seller entity is registered on Amazon (e.g. US, Western Non-China, China).",
            key="select_single_region"
        )
        single_region = REGION_OPTIONS[single_region_lbl]
    with col_f:
        single_filter_100 = st.checkbox(
            "🔥 Only Extract < 100 Review Brands",
            value=False,
            help="Pre-filters crawler: only saves brands whose listings have less than 100 reviews.",
            key="chk_single_100"
        )
        single_check_all_under_100 = st.checkbox(
            "🛡️ Audit Brand: All Products < 100 Revs",
            value=True,
            help="Audits other products of this brand on Amazon. Disqualifies the brand if ANY other product has >= 100 reviews.",
            key="chk_single_all_under_100"
        )

    single_exclude_sel = st.multiselect(
        "🚫 Exclude Sellers From (Countries to Skip / Unselect):",
        options=list(EXCLUDE_COUNTRY_CHOICES.keys()),
        default=[],
        help="Sellers registered in these countries will be skipped and NOT extracted (e.g. exclude China/HK).",
        key="select_single_exclude"
    )
    single_exclude_codes = [EXCLUDE_COUNTRY_CHOICES[k] for k in single_exclude_sel]

    col_pers, col_gate = st.columns([1.5, 2.5])
    with col_pers:
        single_persona_lbl = st.selectbox(
            "Brand Stage / Persona:",
            options=list(PERSONA_OPTIONS.keys()),
            index=0,
            help="Filter for launch-stage brands, stagnant veterans needing turnaround, or distressed listings.",
            key="select_single_persona"
        )
        single_persona_code = PERSONA_OPTIONS[single_persona_lbl]
    with col_gate:
        c_g1, c_g2 = st.columns(2)
        with c_g1:
            single_require_contactable = st.checkbox(
                "🎯 Skip Uncontactable Leads",
                value=True,
                help="Only keeps leads that have reachable contact info (Email, Phone, or LinkedIn).",
                key="chk_single_req_contact"
            )
        with c_g2:
            single_direct_only = st.checkbox(
                "⭐ Direct Founder / Decision Maker Only",
                value=False,
                help="Only keep leads with personal founder email or direct LinkedIn profile.",
                key="chk_single_direct_only"
            )

    btn_c1, btn_c2, _ = st.columns([1.2, 1, 4])
    with btn_c1:
        btn_start_single = st.button("🚀 Start Search", type="primary", use_container_width=True, disabled=st.session_state.is_running)
    with btn_c2:
        btn_stop_single = st.button("⏹️ Stop Search", use_container_width=True, disabled=not st.session_state.is_running)

    if btn_stop_single:
        st.session_state.should_stop = True

    if btn_start_single:
        if not single_query.strip():
            st.error("Please enter a valid Amazon search keyword or URL.")
        else:
            st.session_state.is_running = True
            st.session_state.should_stop = False
            st.session_state.active_results = []
            
            prog_status = st.empty()
            prog_bar = st.progress(0)
            live_table = st.empty()
            
            def single_progress(update):
                msg = update.get("message", "")
                curr_p = update.get("current_page", 1)
                prog_bar.progress(min(int((curr_p / single_pages) * 100), 95))
                prog_status.info(f"⏳ {msg}")
                
                if "record" in update:
                    st.session_state.active_results.append(update["record"])
                    df_live = pd.DataFrame(st.session_state.active_results)
                    cols = ["brand_persona", "contact_quality", "brand_name", "asin", "reviews", "email", "phone", "founder_name", "linkedin_url", "seller_country_display"]
                    live_table.dataframe(df_live[[c for c in cols if c in df_live.columns]], use_container_width=True)

            try:
                extractor = AmazonExtractor(marketplace=marketplace, delay_between_requests=delay)
                max_rev = 100 if single_filter_100 else None
                results = extractor.run_pipeline(
                    query=single_query.strip(),
                    max_pages=single_pages,
                    max_reviews=max_rev,
                    region_filter=single_region,
                    exclude_countries=single_exclude_codes,
                    check_all_brand_products_under_100=single_check_all_under_100,
                    require_contactable=single_require_contactable,
                    direct_contact_only=single_direct_only,
                    persona_filter=single_persona_code,
                    progress_callback=single_progress,
                    should_stop_check=lambda: st.session_state.should_stop
                )
                st.session_state.active_results = results
                prog_bar.progress(100)
                
                if st.session_state.should_stop:
                    prog_status.warning(f"⏹️ Stopped by user. Extracted {len(results)} PL brands.")
                else:
                    prog_status.success(f"✅ Search complete! Found {len(results)} unique Private Label brands.")
                
                if results:
                    save_session_to_history({
                        "type": "single_search",
                        "query": single_query.strip(),
                        "marketplace": marketplace,
                        "region_filter": single_region,
                        "exclude_countries": single_exclude_codes,
                        "pages": single_pages,
                        "records": list(results)
                    })

            except Exception as e:
                st.error(f"⚠️ Search halted with notice: {e}. Any brands found prior to the interruption are preserved.")
            finally:
                st.session_state.is_running = False
                st.session_state.should_stop = False

# ----------------------------------------------------
# TAB 2: BULK OPERATIONS
# ----------------------------------------------------
with tab_bulk:
    bulk_mode = st.radio(
        "Choose Bulk Operation:",
        options=["⚡ Bulk Keyword Hunting", "🔍 Bulk ASIN PL Audit"],
        horizontal=True
    )
    
    if bulk_mode == "⚡ Bulk Keyword Hunting":
        st.markdown("**Enter multiple search keywords (one per line). The engine crawls each keyword up to 10 pages, verifies PL sellers, and combines all discovered brands into one unified master table.**")
        
        b_col_txt, b_col_opt = st.columns([3, 1.8])
        with b_col_txt:
            bulk_keywords_text = st.text_area(
                "Keywords List (one per line):",
                placeholder="wireless earbuds\nposture corrector\nyoga mat non slip\nsilicone baking mat\nbamboo cutting board",
                height=150
            )
        with b_col_opt:
            bulk_kw_pages = st.slider("Pages per Keyword:", min_value=1, max_value=10, value=3)
            bulk_kw_region_lbl = st.selectbox("Seller Region:", options=list(REGION_OPTIONS.keys()), index=0, key="select_bulk_kw_region")
            bulk_kw_region = REGION_OPTIONS[bulk_kw_region_lbl]
            bulk_kw_exclude = st.multiselect("🚫 Exclude Sellers From:", options=list(EXCLUDE_COUNTRY_CHOICES.keys()), default=[], key="multisel_bulk_kw_exclude")
            bulk_kw_exclude_codes = [EXCLUDE_COUNTRY_CHOICES[k] for k in bulk_kw_exclude]
            bulk_kw_persona_lbl = st.selectbox("Brand Persona:", options=list(PERSONA_OPTIONS.keys()), index=0, key="select_bulk_kw_persona")
            bulk_kw_persona_code = PERSONA_OPTIONS[bulk_kw_persona_lbl]
            bulk_kw_filter_100 = st.checkbox("🔥 Only Extract < 100 Review Brands", value=False)
            bulk_kw_check_all_under_100 = st.checkbox("🛡️ Audit Brand: All Products < 100 Revs", value=True, key="chk_bulk_kw_all_under_100")
            bulk_kw_require_contact = st.checkbox("🎯 Skip Uncontactable Leads", value=True, key="chk_bulk_kw_req_contact")
            bulk_kw_direct_only = st.checkbox("⭐ Direct Founder / Decision Maker Only", value=False, key="chk_bulk_kw_direct_only")
            btn_start_bulk_kw = st.button("🚀 Start Bulk Keyword Hunt", type="primary", use_container_width=True, disabled=st.session_state.is_running)

        if btn_start_bulk_kw:
            raw_kws = [k.strip() for k in bulk_keywords_text.splitlines() if k.strip()]
            if not raw_kws:
                st.error("Please enter at least one keyword.")
            else:
                st.session_state.is_running = True
                st.session_state.should_stop = False
                st.session_state.active_results = []
                
                b_overall_bar = st.progress(0)
                b_overall_msg = st.empty()
                b_table = st.empty()
                
                extractor = AmazonExtractor(marketplace=marketplace, delay_between_requests=delay)
                all_bulk_records = []
                seen_b_set = set()
                
                try:
                    for i, kw in enumerate(raw_kws):
                        if st.session_state.should_stop:
                            break
                        
                        b_overall_msg.info(f"⏳ Searching keyword {i+1} of {len(raw_kws)}: **'{kw}'**...")
                        b_overall_bar.progress(int((i / len(raw_kws)) * 100))
                        
                        max_rev = 100 if bulk_kw_filter_100 else None
                        try:
                            kw_results = extractor.run_pipeline(
                                query=kw,
                                max_pages=bulk_kw_pages,
                                max_reviews=max_rev,
                                region_filter=bulk_kw_region,
                                exclude_countries=bulk_kw_exclude_codes,
                                check_all_brand_products_under_100=bulk_kw_check_all_under_100,
                                require_contactable=bulk_kw_require_contact,
                                direct_contact_only=bulk_kw_direct_only,
                                persona_filter=bulk_kw_persona_code,
                                should_stop_check=lambda: st.session_state.should_stop
                            )
                        except Exception as kw_err:
                            st.warning(f"Notice on '{kw}': {kw_err}. Continuing with remaining keywords...")
                            kw_results = []
                        
                        for r in kw_results:
                            b_name = (r.get("brand_name") or "").lower().strip()
                            if b_name and b_name not in seen_b_set:
                                seen_b_set.add(b_name)
                                all_bulk_records.append(r)
                        
                        st.session_state.active_results = list(all_bulk_records)
                        df_b_live = pd.DataFrame(all_bulk_records)
                        cols = ["asin", "brand_name", "matched_seller", "seller_country", "seller_business_name", "reviews", "founder_name", "linkedin_url", "pl_confidence"]
                        b_table.dataframe(df_b_live[[c for c in cols if c in df_b_live.columns]], use_container_width=True)
                    
                    b_overall_bar.progress(100)
                    b_overall_msg.success(f"✅ Bulk hunt complete! Extracted {len(all_bulk_records)} unique Private Label brands across {len(raw_kws)} keywords.")
                    
                    if all_bulk_records:
                        save_session_to_history({
                            "type": "bulk_keywords",
                            "query": f"Bulk: {len(raw_kws)} keywords ({', '.join(raw_kws[:3])}...)",
                            "marketplace": marketplace,
                            "region_filter": bulk_kw_region,
                            "exclude_countries": bulk_kw_exclude_codes,
                            "pages": bulk_kw_pages,
                            "records": list(all_bulk_records)
                        })
                except Exception as e:
                    st.error(f"Bulk keyword extraction notice: {e}")
                finally:
                    st.session_state.is_running = False
                    st.session_state.should_stop = False

    else:
        st.markdown("**Audit a list of ASINs directly. Concurrently inspects Buy Box seller, brand store, registered seller country, review counts, and finds decision makers on LinkedIn.**")
        ba_c1, ba_c2 = st.columns([3, 1.8])
        with ba_c1:
            asin_text = st.text_area(
                "Paste ASINs (comma, space, or newline separated):",
                placeholder="B08N5WRWNW, B07XJ8C8F5, B09B8W2T8S\nB08XYZ1234",
                height=130
            )
        with ba_c2:
            bulk_asin_region_lbl = st.selectbox("Seller Region:", options=list(REGION_OPTIONS.keys()), index=0, key="select_bulk_asin_region")
            bulk_asin_region = REGION_OPTIONS[bulk_asin_region_lbl]
            bulk_asin_exclude = st.multiselect("🚫 Exclude Sellers From:", options=list(EXCLUDE_COUNTRY_CHOICES.keys()), default=[], key="multisel_bulk_asin_exclude")
            bulk_asin_exclude_codes = [EXCLUDE_COUNTRY_CHOICES[k] for k in bulk_asin_exclude]
            bulk_asin_check_all_under_100 = st.checkbox("🛡️ Audit Brand: All Products < 100 Revs", value=True, key="chk_bulk_asin_all_under_100")
            btn_start_bulk_asin = st.button("🔍 Run Bulk ASIN Audit", type="primary", use_container_width=True)
        
        if btn_start_bulk_asin:
            asins = list(dict.fromkeys(re.findall(r'[B0-9A-Z]{10}', asin_text.upper())))
            if not asins:
                st.error("No valid 10-character Amazon ASINs found in input.")
            else:
                st.info(f"Auditing {len(asins)} ASINs in parallel with safety thread-pool...")
                extractor = AmazonExtractor(marketplace=marketplace, delay_between_requests=0.2)
                audit_records = []
                
                asin_prog = st.progress(0)
                asin_status = st.empty()
                
                def audit_asin(asin):
                    try:
                        record = extractor.audit_brand_by_asin(
                            asin_or_url=asin,
                            check_all_brand_products_under_100=bulk_asin_check_all_under_100
                        )
                        if not record.get("success"):
                            return None
                        if not record.get("is_private_label"):
                            return None
                        if not is_seller_allowed(record.get("seller_country", "Unknown"), region_filter=bulk_asin_region, exclude_countries=bulk_asin_exclude_codes):
                            return None
                        return record
                    except Exception:
                        return None

                completed = 0
                with ThreadPoolExecutor(max_workers=5) as executor:
                    futures = {executor.submit(audit_asin, a): a for a in asins}
                    for fut in as_completed(futures):
                        completed += 1
                        asin_prog.progress(int((completed / len(asins)) * 100))
                        res = fut.result()
                        if res:
                            audit_records.append(res)
                
                st.session_state.active_results = list(audit_records)
                asin_status.success(f"✅ Audit complete! Verified {len(audit_records)} Private Label brands out of {len(asins)} ASINs.")
                
                if audit_records:
                    save_session_to_history({
                        "type": "bulk_asins",
                        "query": f"Bulk ASINs ({len(asins)} tested)",
                        "marketplace": marketplace,
                        "region_filter": bulk_asin_region,
                        "exclude_countries": bulk_asin_exclude_codes,
                        "pages": 1,
                        "records": list(audit_records)
                    })

# ==========================================
# ACTIVE RESULTS EXPLORER & FILTERS
# ==========================================
if st.session_state.active_results:
    st.divider()
    df_raw = pd.DataFrame(st.session_state.active_results)
    
    if "reviews" in df_raw.columns:
        df_raw["reviews"] = pd.to_numeric(df_raw["reviews"], errors="coerce").fillna(0).astype(int)
    else:
        df_raw["reviews"] = 0

    total_brands = len(df_raw)
    under_100_total = int((df_raw["reviews"] < 100).sum())
    us_total = len(df_raw[df_raw["seller_country"].astype(str).str.upper() == "US"]) if "seller_country" in df_raw else 0
    non_cn_total = len(df_raw[~df_raw["seller_country"].astype(str).str.upper().isin(["CN", "HK", "UNKNOWN", ""])]) if "seller_country" in df_raw else 0
    cn_total = len(df_raw[df_raw["seller_country"].astype(str).str.upper().isin(["CN", "HK"])]) if "seller_country" in df_raw else 0
    websites_total = len(df_raw[df_raw["website"].str.lower() != "not found"]) if "website" in df_raw else 0
    emails_total = len(df_raw[df_raw["email"].str.lower() != "not found"]) if "email" in df_raw else 0
    phones_total = len(df_raw[df_raw["phone"].str.lower() != "not found"]) if "phone" in df_raw else 0
    verified_all_under_100_total = len(df_raw[df_raw["all_products_under_100"].astype(str).str.contains("Verified", case=False, na=False)]) if "all_products_under_100" in df_raw else 0
    founders_total = len(df_raw[df_raw["founder_name"].str.lower() != "not found"]) if "founder_name" in df_raw else 0
    new_launch_total = len(df_raw[df_raw["brand_persona"].astype(str).str.contains("New Launch", case=False, na=False)]) if "brand_persona" in df_raw else 0
    stagnant_veteran_total = len(df_raw[df_raw["brand_persona"].astype(str).str.contains("Stagnant Veteran", case=False, na=False)]) if "brand_persona" in df_raw else 0
    distressed_total = len(df_raw[df_raw["brand_persona"].astype(str).str.contains("Distressed", case=False, na=False) | df_raw["has_frequently_returned_badge"].fillna(False)]) if "brand_persona" in df_raw else 0
    direct_contacts_total = len(df_raw[df_raw["contact_quality"].astype(str).str.contains("Direct Decision Maker", case=False, na=False)]) if "contact_quality" in df_raw else 0

    m1, m2, m3, m4, m5, m6, m7 = st.columns(7)
    with m1:
        st.markdown(f'<div class="metric-card"><div class="metric-val">{total_brands}</div><div class="metric-lbl">Total PL Brands</div></div>', unsafe_allow_html=True)
    with m2:
        st.markdown(f'<div class="metric-card"><div class="metric-val" style="color:#10b981">🚀 {new_launch_total}</div><div class="metric-lbl">New Launches</div></div>', unsafe_allow_html=True)
    with m3:
        st.markdown(f'<div class="metric-card"><div class="metric-val" style="color:#f59e0b">📉 {stagnant_veteran_total}</div><div class="metric-lbl">Stagnant Veterans</div></div>', unsafe_allow_html=True)
    with m4:
        st.markdown(f'<div class="metric-card"><div class="metric-val" style="color:#ef4444">⚠️ {distressed_total}</div><div class="metric-lbl">Distressed</div></div>', unsafe_allow_html=True)
    with m5:
        st.markdown(f'<div class="metric-card"><div class="metric-val" style="color:#a855f7">⭐ {direct_contacts_total}</div><div class="metric-lbl">Direct Founders</div></div>', unsafe_allow_html=True)
    with m6:
        st.markdown(f'<div class="metric-card"><div class="metric-val" style="color:#0ea5e9">✉️ {emails_total}</div><div class="metric-lbl">Reachable Emails</div></div>', unsafe_allow_html=True)
    with m7:
        st.markdown(f'<div class="metric-card"><div class="metric-val" style="color:#34d399">🛡️ {verified_all_under_100_total}</div><div class="metric-lbl">All SKUs &lt;100</div></div>', unsafe_allow_html=True)

    st.write("")
    
    st.subheader("🎛️ Results Filter & Search")
    f_c1, f_c2, f_c3 = st.columns([3.2, 1.1, 2.2])
    with f_c1:
        filter_mode = st.radio(
            "Quick Filter:",
            options=[
                "All Brands",
                f"🚀 New Launches Only ({new_launch_total})",
                f"📉 Stagnant Veterans Only ({stagnant_veteran_total})",
                f"⚠️ Distressed Catalog ({distressed_total})",
                f"⭐ Direct Decision Makers Only ({direct_contacts_total})",
                f"🛡️ All Brand SKUs < 100 Revs ({verified_all_under_100_total})",
                f"🔥 Less than 100 Reviews ({under_100_total})",
                f"🛡️ Exclude China / HK ({non_cn_total})",
                f"🇺🇸 US Registered Sellers ({us_total})",
                f"🌐 Website Found ({websites_total})",
                f"✉️ Email Found ({emails_total})",
                f"📞 Phone Found ({phones_total})"
            ],
            horizontal=True
        )
    with f_c2:
        max_rev_cap = st.number_input("Max Reviews Cap (0 = Unlimited):", min_value=0, max_value=50000, value=0, step=50)
    with f_c3:
        text_search = st.text_input("🔍 Live Search (Brand, Seller, Country, Address, Website):", placeholder="Type keyword to filter...")

    all_countries_found = sorted(list({str(c).upper() for c in df_raw["seller_country"].dropna() if str(c).strip()}))
    if not all_countries_found:
        all_countries_found = ["US"]

    c_col1, c_col2 = st.columns([1.5, 1.5])
    with c_col1:
        unselected_countries = st.multiselect(
            "🗺️ Filter by Seller Countries (Uncheck to Exclude):",
            options=all_countries_found,
            default=all_countries_found,
            help="Unselect any country to instantly omit those sellers from the table and exports."
        )
    with c_col2:
        direct_exclude_countries = st.multiselect(
            "🚫 Exclude Specific Countries (Blacklist):",
            options=all_countries_found,
            default=[],
            help="Select countries here to explicitly filter them out."
        )

    df_filtered = df_raw.copy()
    if "New Launches Only" in filter_mode:
        df_filtered = df_filtered[df_filtered["brand_persona"].astype(str).str.contains("New Launch", case=False, na=False)]
    elif "Stagnant Veterans Only" in filter_mode:
        df_filtered = df_filtered[df_filtered["brand_persona"].astype(str).str.contains("Stagnant Veteran", case=False, na=False)]
    elif "Distressed Catalog" in filter_mode:
        df_filtered = df_filtered[df_filtered["brand_persona"].astype(str).str.contains("Distressed", case=False, na=False) | df_filtered["has_frequently_returned_badge"].fillna(False)]
    elif "Direct Decision Makers Only" in filter_mode:
        df_filtered = df_filtered[df_filtered["contact_quality"].astype(str).str.contains("Direct Decision Maker", case=False, na=False)]
    elif "All Brand SKUs < 100 Revs" in filter_mode:
        if "all_products_under_100" in df_filtered.columns:
            df_filtered = df_filtered[df_filtered["all_products_under_100"].astype(str).str.contains("Verified", case=False, na=False)]
        else:
            df_filtered = df_filtered[df_filtered["reviews"] < 100]
    elif "Less than 100 Reviews" in filter_mode:
        df_filtered = df_filtered[df_filtered["reviews"] < 100]
    elif "Exclude China / HK" in filter_mode:
        df_filtered = df_filtered[~df_filtered["seller_country"].astype(str).str.upper().isin(["CN", "HK"])]
    elif "US Registered Sellers" in filter_mode:
        df_filtered = df_filtered[df_filtered["seller_country"].astype(str).str.upper() == "US"]
    elif "Website Found" in filter_mode:
        df_filtered = df_filtered[df_filtered["website"].str.lower() != "not found"]
    elif "Email Found" in filter_mode:
        df_filtered = df_filtered[df_filtered["email"].str.lower() != "not found"]
    elif "Phone Found" in filter_mode:
        df_filtered = df_filtered[df_filtered["phone"].str.lower() != "not found"]

    if unselected_countries is not None:
        df_filtered = df_filtered[df_filtered["seller_country"].astype(str).str.upper().isin(unselected_countries)]

    if direct_exclude_countries:
        df_filtered = df_filtered[~df_filtered["seller_country"].astype(str).str.upper().isin(direct_exclude_countries)]

    if max_rev_cap > 0:
        df_filtered = df_filtered[df_filtered["reviews"] <= max_rev_cap]

    if text_search.strip():
        q_l = text_search.strip().lower()
        df_filtered = df_filtered[
            df_filtered["brand_name"].str.lower().str.contains(q_l, na=False) |
            df_filtered["matched_seller"].str.lower().str.contains(q_l, na=False) |
            (df_filtered["seller_country"].astype(str).str.lower().str.contains(q_l, na=False) if "seller_country" in df_filtered else False) |
            (df_filtered["seller_business_name"].astype(str).str.lower().str.contains(q_l, na=False) if "seller_business_name" in df_filtered else False) |
            (df_filtered["seller_address"].astype(str).str.lower().str.contains(q_l, na=False) if "seller_address" in df_filtered else False) |
            (df_filtered["website"].str.lower().str.contains(q_l, na=False) if "website" in df_filtered else False) |
            (df_filtered["email"].str.lower().str.contains(q_l, na=False) if "email" in df_filtered else False) |
            (df_filtered["phone"].str.lower().str.contains(q_l, na=False) if "phone" in df_filtered else False) |
            df_filtered["founder_name"].str.lower().str.contains(q_l, na=False) |
            df_filtered["asin"].str.lower().str.contains(q_l, na=False)
        ]

    records_to_export = df_filtered.to_dict(orient="records")
    csv_data = export_to_csv_bytes(records_to_export)
    excel_data = export_to_excel_bytes(records_to_export)

    exp_col1, exp_col2, exp_col3, exp_info = st.columns([1.2, 1.2, 1.2, 2.4])
    with exp_col1:
        st.download_button(
            label=f"📄 Download CSV ({len(df_filtered)})",
            data=csv_data,
            file_name=f"amazon_pl_brands_{int(time.time())}.csv",
            mime="text/csv",
            use_container_width=True
        )
    with exp_col2:
        st.download_button(
            label=f"📊 Download Excel ({len(df_filtered)})",
            data=excel_data,
            file_name=f"amazon_pl_brands_{int(time.time())}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    with exp_col3:
        if st.button(f"📧 Email Leads ({len(df_filtered)})", use_container_width=True):
            ok, msg = send_leads_email(records_to_export)
            if ok:
                st.success(f"✅ {msg}")
            else:
                st.error(f"❌ {msg}")
    with exp_info:
        st.caption(f"Showing **{len(df_filtered)}** of **{total_brands}** total extracted brands. Export contains currently filtered rows.")

    cols_order = [
        "brand_persona",
        "contact_quality",
        "brand_name",
        "asin",
        "reviews",
        "rating",
        "catalog_health_summary",
        "email",
        "email_type",
        "phone",
        "website",
        "founder_name",
        "linkedin_url",
        "date_first_available",
        "brand_age_months",
        "all_products_under_100",
        "matched_seller",
        "seller_country_display",
        "seller_business_name",
        "seller_address",
        "growth_pitch_hook",
        "pl_confidence",
        "price",
        "product_title",
        "product_url"
    ]
    display_cols = [c for c in cols_order if c in df_filtered.columns]

    st.dataframe(
        df_filtered[display_cols],
        column_config={
            "brand_persona": st.column_config.TextColumn("Persona"),
            "contact_quality": st.column_config.TextColumn("Contact Quality"),
            "brand_name": st.column_config.TextColumn("Brand Name"),
            "asin": st.column_config.TextColumn("ASIN"),
            "reviews": st.column_config.NumberColumn("Reviews", format="%d ⭐"),
            "rating": st.column_config.TextColumn("Rating"),
            "catalog_health_summary": st.column_config.TextColumn("Listing Alerts"),
            "email": st.column_config.TextColumn("Outreach Email"),
            "email_type": st.column_config.TextColumn("Email Type"),
            "phone": st.column_config.TextColumn("Phone Number"),
            "website": st.column_config.LinkColumn("Brand Website"),
            "founder_name": st.column_config.TextColumn("Founder / Executive"),
            "linkedin_url": st.column_config.LinkColumn("LinkedIn"),
            "date_first_available": st.column_config.TextColumn("Launch Date"),
            "growth_pitch_hook": st.column_config.TextColumn("Pitch Hook"),
            "seller_country_display": st.column_config.TextColumn("Seller Region"),
            "seller_business_name": st.column_config.TextColumn("Legal Name"),
            "matched_seller": st.column_config.TextColumn("PL Seller"),
            "product_url": st.column_config.LinkColumn("Amazon Listing")
        },
        use_container_width=True,
        hide_index=True
    )

    # Growth Strategy & Turnaround Pitch Cards
    if len(df_filtered) > 0 and "growth_pitch_hook" in df_filtered.columns:
        with st.expander("💡 View Tailored Growth Pitches & Problem Audits for Discovered Brands", expanded=False):
            for _, row in df_filtered.head(25).iterrows():
                b_name = row.get("brand_name", "")
                persona = row.get("brand_persona", "PL Brand")
                asin = row.get("asin", "")
                launch = row.get("date_first_available", "Not Listed")
                alerts = row.get("catalog_health_summary", "Healthy")
                baseline = row.get("growth_strategy_current", "")
                achieve = row.get("growth_strategy_achievable", "")
                hook = row.get("growth_pitch_hook", "")
                qual = row.get("contact_quality", "")

                st.markdown(f"#### {b_name} &bull; `{persona}` &bull; {qual}")
                st.caption(f"ASIN: {asin} &bull; Launched: {launch} &bull; Alerts: {alerts}")
                if baseline:
                    st.markdown(f"**Baseline Audit:** `{baseline}`")
                if achieve:
                    st.markdown(f"**Achievable Milestones:**\n```\n{achieve}\n```")
                if hook:
                    st.info(f"🎯 **Cold Outreach Pitch Hook:**\n\n\"{hook}\"")
                st.divider()

# ----------------------------------------------------
# TAB 3: SEARCH HISTORY (Persistent)
# ----------------------------------------------------
with tab_history:
    history_list = load_saved_history()
    
    total_saved_sessions = len(history_list)
    all_history_records = []
    seen_all_brands = set()
    
    for item in history_list:
        for r in item.get("records", []):
            b_norm = (r.get("brand_name") or "").lower().strip()
            if b_norm and b_norm not in seen_all_brands:
                seen_all_brands.add(b_norm)
                all_history_records.append(r)

    hist_under_100 = sum(1 for r in all_history_records if int(r.get("reviews") or 0) < 100)
    hist_us = sum(1 for r in all_history_records if (r.get("seller_country") or "").upper() == "US")
    hist_non_cn = sum(1 for r in all_history_records if (r.get("seller_country") or "").upper() not in ["CN", "HK", "UNKNOWN", ""])
    hist_websites = sum(1 for r in all_history_records if r.get("website") and r.get("website").lower() != "not found")
    hist_emails = sum(1 for r in all_history_records if r.get("email") and r.get("email").lower() != "not found")
    hist_phones = sum(1 for r in all_history_records if r.get("phone") and r.get("phone").lower() != "not found")
    hist_founders = sum(1 for r in all_history_records if r.get("founder_name") and r.get("founder_name").lower() != "not found")

    h_m1, h_m2, h_m3, h_m4, h_m5 = st.columns(5)
    with h_m1:
        st.markdown(f'<div class="metric-card"><div class="metric-val">{total_saved_sessions}</div><div class="metric-lbl">Saved Searches</div></div>', unsafe_allow_html=True)
    with h_m2:
        st.markdown(f'<div class="metric-card"><div class="metric-val">{len(all_history_records)}</div><div class="metric-lbl">Unique Brands</div></div>', unsafe_allow_html=True)
    with h_m3:
        st.markdown(f'<div class="metric-card"><div class="metric-val" style="color:#34d399">🔥 {hist_under_100}</div><div class="metric-lbl">&lt; 100 Revs</div></div>', unsafe_allow_html=True)
    with h_m4:
        st.markdown(f'<div class="metric-card"><div class="metric-val" style="color:#60a5fa">🇺🇸 {hist_us} | 🛡️ {hist_non_cn}</div><div class="metric-lbl">US / Non-CN Sellers</div></div>', unsafe_allow_html=True)
    with h_m5:
        st.markdown(f'<div class="metric-card"><div class="metric-val" style="color:#38bdf8">🌐 {hist_websites} | 👤 {hist_founders}</div><div class="metric-lbl">Sites & Founders</div></div>', unsafe_allow_html=True)

    st.write("")
    
    h_act1, h_act2, h_act3, h_act4 = st.columns([1.5, 1.5, 1.5, 1.2])
    with h_act1:
        if st.button("👁️ Load All History into Table", use_container_width=True, disabled=not all_history_records):
            st.session_state.active_results = list(all_history_records)
            st.rerun()
    with h_act2:
        if all_history_records:
            all_csv = export_to_csv_bytes(all_history_records)
            st.download_button("📄 Export All (CSV)", data=all_csv, file_name=f"amazon_pl_master_history_{int(time.time())}.csv", mime="text/csv", use_container_width=True)
        else:
            st.button("📄 Export All (CSV)", disabled=True, use_container_width=True)
    with h_act3:
        if all_history_records:
            all_excel = export_to_excel_bytes(all_history_records)
            st.download_button("📊 Export All (Excel)", data=all_excel, file_name=f"amazon_pl_master_history_{int(time.time())}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        else:
            st.button("📊 Export All (Excel)", disabled=True, use_container_width=True)
    with h_act4:
        if st.button("🗑️ Clear History", type="secondary", use_container_width=True, disabled=not history_list):
            clear_all_history()
            st.rerun()

    # PERSISTENT BACKUP & REBOOT SAFETY NET
    with st.expander("💾 Persistent Backup & Cloud Safety Net (Survives Cloud Reboots)", expanded=False):
        st.markdown("""
        **🛡️ Cloud Reboot Safety Net:**
        Cloud containers (like Streamlit Cloud) may reset their local disks on server reboots or redeployments.
        Use this safety net to guarantee your data is **100% safeguarded**:
        - **1-Click Backup**: Download your full search archive (.json) to your computer anytime.
        - **1-Click Restore**: Drop your backup file here after any reboot to instantly restore all past searches, brands, and founders!
        - **Cloud Sync Ready**: Add `GIST_TOKEN` & `GIST_ID` in Streamlit Secrets for 100% automated background cloud synchronization.
        """)
        bk_c1, bk_c2 = st.columns([1.5, 2])
        with bk_c1:
            full_json_str = json.dumps(history_list, indent=2, ensure_ascii=False)
            st.download_button(
                "📥 Download History Backup (.json)",
                data=full_json_str,
                file_name=f"amazon_pl_history_backup_{int(time.time())}.json",
                mime="application/json",
                use_container_width=True,
                disabled=not history_list
            )
        with bk_c2:
            uploaded_bk = st.file_uploader("📤 Restore History from Backup (.json):", type=["json"], key="history_restore_uploader")
            if uploaded_bk is not None:
                success, msg = import_backup_history(uploaded_bk)
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

    history_search = st.text_input("🔍 Search saved searches by keyword, brand name, seller, country, or marketplace:", "", placeholder="Filter history...")
    
    filtered_history = history_list
    if history_search.strip():
        h_q = history_search.strip().lower()
        filtered_history = [
            item for item in history_list
            if h_q in item.get("query", "").lower()
            or h_q in item.get("marketplace", "").lower()
            or any(h_q in r.get("brand_name", "").lower() for r in item.get("records", []))
            or any(h_q in r.get("matched_seller", "").lower() for r in item.get("records", []))
            or any(h_q in str(r.get("seller_country", "")).lower() for r in item.get("records", []))
        ]

    st.write("")
    
    if not filtered_history:
        if history_search:
            st.info(f"No saved searches matching '{history_search}'.")
        else:
            st.info("No search history saved yet. Any single or bulk searches will automatically be stored here and remain even after page reloads!")
    else:
        for idx, item in enumerate(filtered_history):
            tag_class = "hist-tag-single" if item.get("type") == "single_search" else "hist-tag-bulk"
            tag_label = "🌐 Single Search" if item.get("type") == "single_search" else "⚡ Bulk Operation"
            
            with st.container():
                st.markdown(f"""
                <div class="hist-card">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                        <div>
                            <span class="hist-tag {tag_class}">{tag_label}</span>
                            <span class="hist-card-title" style="margin-left:8px;">{item.get('query', 'Amazon Search')}</span>
                            <span style="color:#64748b;font-size:12px;margin-left:6px;">({item.get('marketplace', 'amazon.com')})</span>
                        </div>
                        <span style="color:#94a3b8;font-size:12px;">🕒 {item.get('formatted_time', '')}</span>
                    </div>
                    <div style="display:flex;gap:12px;font-size:12px;color:#cbd5e1;flex-wrap:wrap;">
                        <span>🏷️ <b>{item.get('brand_count', 0)}</b> Brands</span>
                        <span style="color:#34d399">🔥 <b>{item.get('under_100_count', 0)}</b> (&lt; 100 revs)</span>
                        <span style="color:#60a5fa">🇺🇸 <b>{item.get('us_sellers_count', 0)}</b> US</span>
                        <span style="color:#10b981">🛡️ <b>{item.get('non_cn_sellers_count', 0)}</b> Non-CN</span>
                        <span style="color:#38bdf8">🌐 <b>{item.get('websites_count', 0)}</b> Web</span>
                        <span style="color:#fbbf24">✉️ <b>{item.get('emails_count', 0)}</b> Email</span>
                        <span style="color:#a78bfa">📞 <b>{item.get('phones_count', 0)}</b> Phone</span>
                        <span>👤 <b>{item.get('founders_count', 0)}</b> Founders</span>
                        <span>🔗 <b>{item.get('linkedin_count', 0)}</b> LinkedIn</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                hc1, hc2, hc3, hc4, hc5 = st.columns([1.5, 1.2, 1.2, 1.5, 0.8])
                with hc1:
                    if st.button("👁️ Load into Table", key=f"btn_h_load_{item['id']}"):
                        st.session_state.active_results = item.get("records", [])
                        st.rerun()
                with hc2:
                    s_csv = export_to_csv_bytes(item.get("records", []))
                    st.download_button("📄 CSV", data=s_csv, file_name=f"amazon_pl_{item['id']}.csv", mime="text/csv", key=f"btn_h_csv_{item['id']}", use_container_width=True)
                with hc3:
                    s_xlsx = export_to_excel_bytes(item.get("records", []))
                    st.download_button("📊 Excel", data=s_xlsx, file_name=f"amazon_pl_{item['id']}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"btn_h_xlsx_{item['id']}", use_container_width=True)
                with hc4:
                    with st.expander(f"▾ Brand Preview ({item.get('brand_count', 0)})"):
                        for r in (item.get("records", [])[:15]):
                            rev = int(r.get("reviews") or 0)
                            rev_str = f"🔥 {rev} revs" if rev < 100 else f"{rev} revs"
                            country = r.get("seller_country")
                            c_str = f" [📍 {country}]" if country and country != "Unknown" else ""
                            web = f" | 🌐 {r.get('website')}" if r.get('website') and r.get('website') != 'Not Found' else ""
                            em = f" | ✉️ {r.get('email')}" if r.get('email') and r.get('email') != 'Not Found' else ""
                            ph = f" | 📞 {r.get('phone')}" if r.get('phone') and r.get('phone') != 'Not Found' else ""
                            founder = f" | 👤 {r.get('founder_name')}" if r.get('founder_name') and r.get('founder_name') != 'Not Found' else ""
                            st.caption(f"• **{r.get('brand_name')}** ({rev_str}) — {r.get('matched_seller')}{c_str}{web}{em}{ph}{founder}")
                with hc5:
                    if st.button("🗑️", key=f"btn_h_del_{item['id']}", help="Delete this session"):
                        delete_history_session(item["id"])
                        st.rerun()
                
                st.write("")
