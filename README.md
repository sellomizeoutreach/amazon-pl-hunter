# 📦 Amazon Private Label & LinkedIn Decision Maker Extractor

A high-performance Python-powered tool and Chrome/Edge browser extension that hunts for **Private Label (PL) brands** on Amazon search & category pages (up to 10 pages), verifies seller ownership across all offers (even when someone else holds the Buy Box), deduplicates repeated brands, and discovers the brand's **Founders / CEOs / Decision Makers** and their **LinkedIn profile links**.

---

## 🚀 Key Features

1. **Multi-Page Amazon Search Crawler (1 to 10 Pages)**:
   - Search by any keyword (e.g. `wireless earbuds`, `posture corrector`) or paste an Amazon category browse URL.
   - Crawls up to 10 consecutive pages automatically.
   - Bypasses Amazon anti-bot shields and CAPTCHAs via Chrome TLS impersonation (`curl_cffi`).

2. **Smart Private Label (PL) Verification & Multi-Seller Check**:
   - Compares Brand Name with Buy Box seller name.
   - **Checks ALL other sellers**: If a hijacker or reseller temporarily holds the Buy Box, the tool inspects all sellers on the listing to find if the brand owner is present.
   - Normalizes names by stripping stop-words (`Direct`, `Official`, `Store`, `LLC`, `Inc`, `US`, etc.) and performs token & fuzzy similarity checks.
   - Excludes multi-seller wholesale / retail arbitrage products (e.g. brands with 15+ arbitrage sellers where brand owner is absent).

3. **Strict Brand Deduplication**:
   - Guarantees that duplicate brands are never repeated across multiple ASINs or pages. Each unique brand is captured once.

4. **Decision Maker & LinkedIn Profile Discovery**:
   - Searches for the Founder, Co-Founder, CEO, or Owner of each extracted brand.
   - Extracts their full name, job title, and verified `linkedin.com/in/...` profile link.
   - Output format:
     - If all found: `ASIN`, `Brand Name`, `Founder Name`, `LinkedIn URL`
     - If LinkedIn not found: `ASIN`, `Brand Name`, `Founder Name`, `Not Found`
     - If neither found: `ASIN`, `Brand Name`, `Not Found`, `Not Found`

5. **Exportable Data**:
   - 1-click export to **CSV** and styled **Excel (.xlsx)** spreadsheets.

6. **Persistent Chrome / Edge Side Panel**:
   - Opens docked permanently inside Chrome's native **Side Panel** on the right.
   - **Never closes** when you click on Amazon listings, scroll, or switch tabs!
   - Resizable width and full-height live results table.
   - Dual mode: also includes a standalone Streamlit desktop dashboard.

---

## 📁 Project Architecture

```
Extract Exten/
├── backend/
│   ├── __init__.py
│   ├── amazon_scraper.py      # Multi-page crawler & deep ASIN seller inspector
│   ├── pl_detector.py         # Private Label evaluation logic (Buybox & all sellers)
│   ├── linkedin_finder.py     # Decision Maker & LinkedIn profile searcher
│   ├── exporter.py            # CSV & Excel generator
│   └── server.py              # FastAPI REST server with CORS for extension
├── extension/                 # Chrome / Edge Extension (Manifest V3)
│   ├── manifest.json
│   ├── popup.html             # Sleek extension UI
│   ├── popup.js               # Extension controller & backend API bridge
│   ├── popup.css              # Dark Amazon styling
│   ├── content.js             # Active tab Amazon DOM scraper
│   └── icons/                 # 16x16, 48x48, 128x128 icons
├── dashboard/
│   └── app.py                 # Streamlit desktop dashboard
├── exports/                   # Default export directory for CSV & Excel files
├── requirements.txt           # Python dependencies
├── start_backend.bat          # 1-click startup for Extension Backend
├── start_dashboard.bat        # 1-click startup for Streamlit Dashboard
└── install_dependencies.bat   # 1-click dependency installer
```

---

## 🛠️ Quick Start Guide

### Step 1: Install Dependencies
Double click **`install_dependencies.bat`** (or run in terminal):
```bash
pip install -r requirements.txt
```

---

### Step 2: Load the Extension in Chrome or Edge
1. Open Google Chrome or Microsoft Edge.
2. In the address bar, go to:
   - Chrome: `chrome://extensions`
   - Edge: `edge://extensions`
3. Toggle on **Developer mode** in the top right corner.
4. Click **Load unpacked**.
5. Select the folder:
   ```
   c:\Antigravet\Extract Exten\extension
   ```
6. The **Amazon PL Hunter** icon will now appear in your browser toolbar! Pin it for quick access.

---

### Step 3: Start the Backend Server
Double click **`start_backend.bat`** (or run in terminal):
```bash
python -m uvicorn backend.server:app --host 127.0.0.1 --port 8000 --reload
```
Keep this terminal open while using the Chrome extension. The extension will automatically display a **🟢 Backend Online** badge.

---

### Step 4: Run Extractions!

#### Using the Chrome Extension:
- **Method 1: Deep Search (1-10 Pages)**:
  1. Click the extension icon.
  2. Type your keyword (e.g. `bluetooth speaker`) or paste a category search URL.
  3. Select your marketplace (US, UK, DE, CA, FR, IT, ES).
  4. Choose number of pages (1 to 10) on the slider.
  5. Click **Start PL Extraction**.
  6. Watch real-time progress and click **CSV** or **Excel** to download.

- **Method 2: Active Tab Scan**:
  1. Browse to any Amazon search result page in Chrome.
  2. Click the extension icon and select the **Active Amazon Tab** tab.
  3. Click **Extract from Active Tab**. The extension inspects all products on your current screen.

---

### Step 5: (Optional) Standalone Desktop Dashboard
If you prefer a full-screen desktop dashboard instead of a browser popup:
1. Double click **`start_dashboard.bat`** (or run `streamlit run dashboard/app.py`).
2. An interactive dashboard will open at `http://localhost:8501`.
3. Filter by brand/founder, view visual discovery rates, and export with 1 click.

---

## 💡 Suggestions & Pro Tips for Best Results

1. **Decision Maker Title Variations**:
   - The tool searches for `Founder`, `Co-Founder`, `CEO`, `Owner`, and `Managing Director`. For smaller private label brands, founders frequently list their title as "Owner" or "Brand Manager" on LinkedIn.
2. **Multi-Seller Buy Box Hijackers**:
   - If a competitor has hijacked the Buy Box, the tool's multi-seller inspector checks the seller roster for the brand name, ensuring you don't miss genuine private label opportunities.
3. **Pacing / Rate Limits**:
   - Amazon search results pages allow steady crawling, but keeping the delay between 0.8s - 1.5s ensures smooth operation across all 10 pages without triggering bot rate limits.
