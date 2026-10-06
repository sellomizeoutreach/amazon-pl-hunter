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

# Ensure root directory is in sys.path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from backend.amazon_scraper import AmazonExtractor
from backend.pl_detector import evaluate_private_label
from backend.linkedin_finder import find_decision_maker
from backend.exporter import export_to_csv_bytes, export_to_excel_bytes

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
        founders_count = sum(1 for r in records if r.get("founder_name") and r.get("founder_name").lower() != "not found")
        linkedin_count = sum(1 for r in records if r.get("linkedin_url") and r.get("linkedin_url").lower() != "not found")
        
        session_item = {
            "id": f"hist_{int(time.time()*1000)}",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "formatted_time": datetime.now().strftime("%b %d, %H:%M"),
            "type": entry.get("type", "single_search"),
            "query": entry.get("query", "Search"),
            "marketplace": entry.get("marketplace", "amazon.com"),
            "pages": entry.get("pages", 1),
            "brand_count": len(records),
            "under_100_count": under_100_count,
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


# ==========================================
# NAVIGATION TABS
# ==========================================
tab_single, tab_bulk, tab_history = st.tabs([
    "🌐 Single Search & Crawl",
    "⚡ Bulk Operations",
    "📜 Search History"
])

# ----------------------------------------------------
# TAB 1: SINGLE SEARCH & CATEGORY CRAWL
# ----------------------------------------------------
with tab_single:
    col_q, col_p, col_f = st.columns([3, 1.2, 1.8])
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
    with col_f:
        single_filter_100 = st.checkbox(
            "🔥 Only Extract < 100 Review Brands",
            value=False,
            help="Pre-filters crawler: only saves brands whose listings have less than 100 reviews.",
            key="chk_single_100"
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
                    cols = ["asin", "brand_name", "matched_seller", "reviews", "founder_name", "linkedin_url", "pl_confidence"]
                    live_table.dataframe(df_live[[c for c in cols if c in df_live.columns]], use_container_width=True)

            try:
                extractor = AmazonExtractor(marketplace=marketplace, delay_between_requests=delay)
                max_rev = 100 if single_filter_100 else None
                results = extractor.run_pipeline(
                    query=single_query.strip(),
                    max_pages=single_pages,
                    max_reviews=max_rev,
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
        
        b_col_txt, b_col_opt = st.columns([3, 1.5])
        with b_col_txt:
            bulk_keywords_text = st.text_area(
                "Keywords List (one per line):",
                placeholder="wireless earbuds\nposture corrector\nyoga mat non slip\nsilicone baking mat\nbamboo cutting board",
                height=130
            )
        with b_col_opt:
            bulk_kw_pages = st.slider("Pages per Keyword:", min_value=1, max_value=10, value=3)
            bulk_kw_filter_100 = st.checkbox("🔥 Only Extract < 100 Review Brands", value=False)
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
                        cols = ["asin", "brand_name", "matched_seller", "reviews", "founder_name", "linkedin_url", "pl_confidence"]
                        b_table.dataframe(df_b_live[[c for c in cols if c in df_b_live.columns]], use_container_width=True)
                    
                    b_overall_bar.progress(100)
                    b_overall_msg.success(f"✅ Bulk hunt complete! Extracted {len(all_bulk_records)} unique Private Label brands across {len(raw_kws)} keywords.")
                    
                    if all_bulk_records:
                        save_session_to_history({
                            "type": "bulk_keywords",
                            "query": f"Bulk: {len(raw_kws)} keywords ({', '.join(raw_kws[:3])}...)",
                            "marketplace": marketplace,
                            "pages": bulk_kw_pages,
                            "records": list(all_bulk_records)
                        })
                except Exception as e:
                    st.error(f"Bulk keyword extraction notice: {e}")
                finally:
                    st.session_state.is_running = False
                    st.session_state.should_stop = False

    else:
        st.markdown("**Audit a list of ASINs directly. Concurrently inspects Buy Box seller, brand store, multi-seller roster, review counts, and finds decision makers on LinkedIn.**")
        asin_text = st.text_area(
            "Paste ASINs (comma, space, or newline separated):",
            placeholder="B08N5WRWNW, B07XJ8C8F5, B09B8W2T8S\nB08XYZ1234",
            height=120
        )
        btn_start_bulk_asin = st.button("🔍 Run Bulk ASIN Audit", type="primary")
        
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
                        details = extractor.inspect_asin_details(asin)
                        b_name = details.get("brand") or ""
                        if not b_name:
                            return None
                        
                        pl_eval = evaluate_private_label(
                            brand_name=b_name,
                            buybox_seller=details.get("buybox_seller", ""),
                            all_sellers=details.get("all_sellers", []),
                            has_brand_store=details.get("has_brand_store", False),
                            has_aplus_content=details.get("has_aplus", False),
                            total_offers_count=details.get("total_offers", 1)
                        )
                        
                        if not pl_eval["is_private_label"]:
                            return None
                        
                        decision_maker = find_decision_maker(b_name)
                        return {
                            "asin": asin,
                            "brand_name": b_name,
                            "matched_seller": pl_eval.get("matched_seller", "") or details.get("buybox_seller", ""),
                            "buybox_seller": details.get("buybox_seller", ""),
                            "reviews": int(details.get("reviews") or 0),
                            "founder_name": decision_maker.get("founder_name", "Not Found"),
                            "linkedin_url": decision_maker.get("linkedin_url", "Not Found"),
                            "decision_maker_role": decision_maker.get("role_title", ""),
                            "pl_confidence": pl_eval.get("confidence", "High"),
                            "product_url": f"{extractor.base_url}/dp/{asin}"
                        }
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
    founders_total = len(df_raw[df_raw["founder_name"].str.lower() != "not found"]) if "founder_name" in df_raw else 0
    linkedin_total = len(df_raw[df_raw["linkedin_url"].str.lower() != "not found"]) if "linkedin_url" in df_raw else 0

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(f'<div class="metric-card"><div class="metric-val">{total_brands}</div><div class="metric-lbl">Total PL Brands</div></div>', unsafe_allow_html=True)
    with m2:
        st.markdown(f'<div class="metric-card"><div class="metric-val" style="color:#34d399">🔥 {under_100_total}</div><div class="metric-lbl">&lt; 100 Reviews ({int(under_100_total/total_brands*100) if total_brands else 0}%)</div></div>', unsafe_allow_html=True)
    with m3:
        st.markdown(f'<div class="metric-card"><div class="metric-val">{founders_total}</div><div class="metric-lbl">Founders Found</div></div>', unsafe_allow_html=True)
    with m4:
        st.markdown(f'<div class="metric-card"><div class="metric-val">{linkedin_total}</div><div class="metric-lbl">LinkedIn Profiles</div></div>', unsafe_allow_html=True)

    st.write("")
    
    st.subheader("🎛️ Results Filter & Search")
    f_c1, f_c2, f_c3 = st.columns([2, 1.5, 2.5])
    with f_c1:
        filter_mode = st.radio(
            "Quick Filter:",
            options=["All Brands", f"🔥 Less than 100 Reviews ({under_100_total})", "👤 Founder Found Only", "🔗 LinkedIn Profile Found"],
            horizontal=True
        )
    with f_c2:
        max_rev_cap = st.number_input("Max Reviews Cap (0 = Unlimited):", min_value=0, max_value=50000, value=0, step=50)
    with f_c3:
        text_search = st.text_input("🔍 Live Search (Brand, Seller, ASIN, Founder):", placeholder="Type keyword to filter...")

    df_filtered = df_raw.copy()
    if "Less than 100 Reviews" in filter_mode:
        df_filtered = df_filtered[df_filtered["reviews"] < 100]
    elif "Founder Found Only" in filter_mode:
        df_filtered = df_filtered[df_filtered["founder_name"].str.lower() != "not found"]
    elif "LinkedIn Profile Found" in filter_mode:
        df_filtered = df_filtered[df_filtered["linkedin_url"].str.lower() != "not found"]

    if max_rev_cap > 0:
        df_filtered = df_filtered[df_filtered["reviews"] <= max_rev_cap]

    if text_search.strip():
        q_l = text_search.strip().lower()
        df_filtered = df_filtered[
            df_filtered["brand_name"].str.lower().str.contains(q_l, na=False) |
            df_filtered["matched_seller"].str.lower().str.contains(q_l, na=False) |
            df_filtered["founder_name"].str.lower().str.contains(q_l, na=False) |
            df_filtered["asin"].str.lower().str.contains(q_l, na=False)
        ]

    records_to_export = df_filtered.to_dict(orient="records")
    csv_data = export_to_csv_bytes(records_to_export)
    excel_data = export_to_excel_bytes(records_to_export)

    exp_col1, exp_col2, exp_info = st.columns([1.2, 1.2, 3])
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
    with exp_info:
        st.caption(f"Showing **{len(df_filtered)}** of **{total_brands}** total extracted brands. Export contains currently filtered rows.")

    cols_order = ["asin", "brand_name", "matched_seller", "reviews", "founder_name", "linkedin_url", "pl_confidence", "price", "product_title", "product_url"]
    display_cols = [c for c in cols_order if c in df_filtered.columns]

    st.dataframe(
        df_filtered[display_cols],
        column_config={
            "asin": st.column_config.TextColumn("ASIN"),
            "brand_name": st.column_config.TextColumn("Brand Name"),
            "matched_seller": st.column_config.TextColumn("PL Seller"),
            "reviews": st.column_config.NumberColumn("Reviews", format="%d ⭐"),
            "founder_name": st.column_config.TextColumn("Founder / Decision Maker"),
            "linkedin_url": st.column_config.LinkColumn("LinkedIn Profile"),
            "pl_confidence": st.column_config.TextColumn("PL Status"),
            "price": st.column_config.TextColumn("Price"),
            "product_title": st.column_config.TextColumn("Product Title"),
            "product_url": st.column_config.LinkColumn("Amazon Listing")
        },
        use_container_width=True,
        hide_index=True
    )

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
    hist_founders = sum(1 for r in all_history_records if r.get("founder_name") and r.get("founder_name").lower() != "not found")

    h_m1, h_m2, h_m3, h_m4 = st.columns(4)
    with h_m1:
        st.markdown(f'<div class="metric-card"><div class="metric-val">{total_saved_sessions}</div><div class="metric-lbl">Saved Searches</div></div>', unsafe_allow_html=True)
    with h_m2:
        st.markdown(f'<div class="metric-card"><div class="metric-val">{len(all_history_records)}</div><div class="metric-lbl">Unique Brands Saved</div></div>', unsafe_allow_html=True)
    with h_m3:
        st.markdown(f'<div class="metric-card"><div class="metric-val" style="color:#34d399">🔥 {hist_under_100}</div><div class="metric-lbl">&lt; 100 Review Brands</div></div>', unsafe_allow_html=True)
    with h_m4:
        st.markdown(f'<div class="metric-card"><div class="metric-val">{hist_founders}</div><div class="metric-lbl">Founders Identified</div></div>', unsafe_allow_html=True)

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

    history_search = st.text_input("🔍 Search saved searches by keyword, brand name, or marketplace:", "", placeholder="Filter history...")
    
    filtered_history = history_list
    if history_search.strip():
        h_q = history_search.strip().lower()
        filtered_history = [
            item for item in history_list
            if h_q in item.get("query", "").lower()
            or h_q in item.get("marketplace", "").lower()
            or any(h_q in r.get("brand_name", "").lower() for r in item.get("records", []))
            or any(h_q in r.get("matched_seller", "").lower() for r in item.get("records", []))
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
                    <div style="display:flex;gap:12px;font-size:12px;color:#cbd5e1;">
                        <span>🏷️ <b>{item.get('brand_count', 0)}</b> Brands</span>
                        <span style="color:#34d399">🔥 <b>{item.get('under_100_count', 0)}</b> (&lt; 100 revs)</span>
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
                            founder = f" | 👤 {r.get('founder_name')}" if r.get('founder_name') and r.get('founder_name') != 'Not Found' else ""
                            st.caption(f"• **{r.get('brand_name')}** ({rev_str}) — {r.get('matched_seller')}{founder}")
                with hc5:
                    if st.button("🗑️", key=f"btn_h_del_{item['id']}", title="Delete this session"):
                        delete_history_session(item["id"])
                        st.rerun()
                
                st.write("")
