import os
import sys
import time
from datetime import datetime
import pandas as pd
import streamlit as st

# Add parent directory to path so backend modules can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.amazon_scraper import AmazonExtractor
from backend.exporter import export_to_csv_bytes, export_to_excel_bytes

st.set_page_config(
    page_title="Amazon Private Label & Decision Maker Hunter",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .main-header {
        font-size: 26px;
        font-weight: 700;
        color: #ff9900;
        margin-bottom: 2px;
    }
    .sub-header {
        font-size: 14px;
        color: #94a3b8;
        margin-bottom: 20px;
    }
    .metric-box {
        background: #1e293b;
        padding: 15px;
        border-radius: 8px;
        border: 1px solid #334155;
        text-align: center;
    }
    .badge-low-rev {
        background-color: rgba(16, 185, 129, 0.2);
        color: #34d399;
        padding: 2px 8px;
        border-radius: 4px;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-header">📦 Amazon Private Label & Decision Maker Hunter</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Crawl up to 10 pages, evaluate Buy Box and all sellers for PL ownership, filter low-competition brands (&lt; 100 reviews), and discover founders on LinkedIn.</div>', unsafe_allow_html=True)

# Session state initialization
if "results" not in st.session_state:
    st.session_state.results = []
if "is_running" not in st.session_state:
    st.session_state.is_running = False
if "should_stop" not in st.session_state:
    st.session_state.should_stop = False
if "history" not in st.session_state:
    st.session_state.history = []

# Sidebar settings
with st.sidebar:
    st.header("⚙️ Search Configuration")
    
    query = st.text_input(
        "Search Keyword or Category URL",
        placeholder="e.g. wireless earbuds or paste URL",
        value=""
    )
    
    marketplace = st.selectbox(
        "Amazon Marketplace",
        options=["amazon.com", "amazon.co.uk", "amazon.de", "amazon.ca", "amazon.fr", "amazon.it", "amazon.es"],
        index=0
    )
    
    max_pages = st.slider(
        "Number of Pages to Crawl",
        min_value=1,
        max_value=10,
        value=3,
        help="Amazon search results will be scraped up to this page count."
    )
    
    filter_under_100_crawl = st.checkbox(
        "🔥 Only Extract < 100 Review Brands",
        value=False,
        help="When checked, only saves brands whose products have less than 100 reviews (Low Competition PL)."
    )
    
    delay = st.slider(
        "Request Delay (seconds)",
        min_value=0.5,
        max_value=3.0,
        value=0.8,
        step=0.1,
        help="Delay between product requests to prevent rate limiting."
    )
    
    st.divider()
    st.markdown("""
    ### 💡 Features & PL Rules:
    - **No Backend Server Needed**: Runs 100% self-contained in Streamlit.
    - **Buy Box & Multi-Seller Check**: Verifies brand ownership across all sellers.
    - **< 100 Reviews Filter**: Discovers low-competition opportunities.
    - **Founder Discovery**: Auto-detects CEOs/Founders on LinkedIn.
    - **Auto-Deduplication**: Never produces duplicate brands.
    """)

# Action buttons
start_col, stop_col, _ = st.columns([1.2, 1, 4])
with start_col:
    start_btn = st.button("🚀 Start PL Hunt", type="primary", use_container_width=True, disabled=st.session_state.is_running)

with stop_col:
    stop_btn = st.button("⏹️ Stop Hunt", use_container_width=True, disabled=not st.session_state.is_running)

if stop_btn:
    st.session_state.should_stop = True

if start_btn:
    if not query.strip():
        st.error("Please enter a search keyword or category URL.")
    else:
        st.session_state.is_running = True
        st.session_state.should_stop = False
        st.session_state.results = []

        status_container = st.empty()
        progress_bar = st.progress(0)
        table_container = st.empty()

        def on_progress(update):
            msg = update.get("message", "")
            curr_page = update.get("current_page", 1)
            pct = min(int((curr_page / max_pages) * 100), 95)
            progress_bar.progress(pct)
            status_container.info(f"⏳ {msg}")

            if "record" in update:
                st.session_state.results.append(update["record"])
                df_temp = pd.DataFrame(st.session_state.results)
                display_cols = ["asin", "brand_name", "matched_seller", "reviews", "founder_name", "linkedin_url", "pl_confidence"]
                table_container.dataframe(
                    df_temp[[c for c in display_cols if c in df_temp.columns]],
                    use_container_width=True
                )

        def check_stop() -> bool:
            return st.session_state.should_stop

        try:
            extractor = AmazonExtractor(marketplace=marketplace, delay_between_requests=delay)
            max_rev_param = 100 if filter_under_100_crawl else None
            final_results = extractor.run_pipeline(
                query=query.strip(),
                max_pages=max_pages,
                max_reviews=max_rev_param,
                progress_callback=on_progress,
                should_stop_check=check_stop
            )
            st.session_state.results = final_results
            progress_bar.progress(100)
            
            if st.session_state.should_stop:
                status_container.warning(f"⏹️ Stopped by user. Extracted {len(final_results)} PL brands.")
            else:
                status_container.success(f"✅ Finished! Found {len(final_results)} unique Private Label brands.")

            # Save to session history
            if final_results:
                st.session_state.history.append({
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                    "query": query.strip(),
                    "marketplace": marketplace,
                    "pages": max_pages,
                    "records": list(final_results),
                    "count": len(final_results)
                })

        except Exception as e:
            st.error(f"Error during extraction: {e}")
        finally:
            st.session_state.is_running = False
            st.session_state.should_stop = False

# Display Results Section
if st.session_state.results:
    st.divider()
    df = pd.DataFrame(st.session_state.results)

    # Ensure reviews column is numeric
    if "reviews" in df.columns:
        df["reviews"] = pd.to_numeric(df["reviews"], errors="coerce").fillna(0).astype(int)
    else:
        df["reviews"] = 0

    # Top Metrics
    total_pl = len(df)
    under_100_count = int((df["reviews"] < 100).sum())
    founders_found = len(df[df["founder_name"].str.lower() != "not found"])
    linkedin_found = len(df[df["linkedin_url"].str.lower() != "not found"])

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Total PL Brands", total_pl)
    with m2:
        st.metric("🔥 < 100 Review Brands", f"{under_100_count} ({int(under_100_count/total_pl*100) if total_pl else 0}%)")
    with m3:
        st.metric("Founders Identified", founders_found)
    with m4:
        st.metric("LinkedIn Profiles", linkedin_found)

    # Filter Bar
    filter_col1, filter_col2 = st.columns([1.5, 2.5])
    with filter_col1:
        view_filter = st.radio(
            "Filter View:",
            options=["All Brands", f"🔥 Less than 100 Reviews ({under_100_count})"],
            horizontal=True
        )
    with filter_col2:
        search_filter = st.text_input("🔍 Search Brand, Seller, or Founder:", "", placeholder="Type to filter...")

    # Apply filters
    display_df = df.copy()
    if "Less than 100 Reviews" in view_filter:
        display_df = display_df[display_df["reviews"] < 100]

    if search_filter.strip():
        q_lower = search_filter.strip().lower()
        display_df = display_df[
            display_df["brand_name"].str.lower().str.contains(q_lower, na=False) |
            display_df["matched_seller"].str.lower().str.contains(q_lower, na=False) |
            display_df["founder_name"].str.lower().str.contains(q_lower, na=False)
        ]

    # Export Buttons (Exports currently filtered view)
    export_records = display_df.to_dict(orient="records")
    csv_bytes = export_to_csv_bytes(export_records)
    excel_bytes = export_to_excel_bytes(export_records)

    exp_c1, exp_c2, _ = st.columns([1.2, 1.2, 3])
    with exp_c1:
        st.download_button(
            label=f"📄 Download CSV ({len(display_df)})",
            data=csv_bytes,
            file_name=f"amazon_pl_brands_{int(time.time())}.csv",
            mime="text/csv",
            use_container_width=True
        )
    with exp_c2:
        st.download_button(
            label=f"📊 Download Excel ({len(display_df)})",
            data=excel_bytes,
            file_name=f"amazon_pl_brands_{int(time.time())}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

    # Data Table (Brand Name and PL Seller together)
    st.subheader(f"📋 Extracted Brands ({len(display_df)} shown)")
    
    preferred_cols = ["asin", "brand_name", "matched_seller", "reviews", "founder_name", "linkedin_url", "pl_confidence", "price", "product_title", "product_url"]
    active_cols = [c for c in preferred_cols if c in display_df.columns]
    
    st.dataframe(
        display_df[active_cols],
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

# Search History Expander
if st.session_state.history:
    with st.expander(f"📜 Search History ({len(st.session_state.history)} searches in this session)"):
        for idx, hist in enumerate(reversed(st.session_state.history)):
            st.markdown(f"**Search #{len(st.session_state.history) - idx}** [{hist['timestamp']}] — **Keyword**: `{hist['query']}` | **Marketplace**: `{hist['marketplace']}` | **Found**: `{hist['count']} brands`")
            if st.button(f"👁️ Load Search #{len(st.session_state.history) - idx} into Table", key=f"hist_load_{idx}"):
                st.session_state.results = hist["records"]
                st.rerun()
