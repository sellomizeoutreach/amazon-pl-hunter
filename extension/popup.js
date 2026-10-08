let BACKEND_URL = "http://127.0.0.1:8000";
const CANDIDATE_URLS = ["http://127.0.0.1:8000", "http://localhost:8000"];

let currentJobId = null;
let pollInterval = null;
let healthCheckInterval = null;
let extractedRecords = [];

// DOM Elements
const backendStatus = document.getElementById("backend-status");
const backendWarning = document.getElementById("backend-warning");
const btnRetryBackend = document.getElementById("btn-retry-backend");

const tabBtnCrawl = document.getElementById("tab-btn-crawl");
const tabBtnActive = document.getElementById("tab-btn-active");
const tabBtnHistory = document.getElementById("tab-btn-history");
const tabCrawl = document.getElementById("tab-crawl");
const tabActive = document.getElementById("tab-active");
const tabHistory = document.getElementById("tab-history");

const historyBadge = document.getElementById("history-badge");
const histStatSearches = document.getElementById("hist-stat-searches");
const histStatBrands = document.getElementById("hist-stat-brands");
const histStatFounders = document.getElementById("hist-stat-founders");
const btnHistLoadAll = document.getElementById("btn-hist-load-all");
const btnHistExportCsv = document.getElementById("btn-hist-export-csv");
const btnHistExportExcel = document.getElementById("btn-hist-export-excel");
const btnHistClearAll = document.getElementById("btn-hist-clear-all");
const historyFilterInput = document.getElementById("history-filter-input");
const historyList = document.getElementById("history-list");

let savedJobIds = new Set();
let cachedHistory = [];

const searchQuery = document.getElementById("search-query");
const marketplaceSelect = document.getElementById("marketplace");
const pageCountInput = document.getElementById("page-count");
const pageValSpan = document.getElementById("page-val");
const btnStartCrawl = document.getElementById("btn-start-crawl");
const btnStopCrawl = document.getElementById("btn-stop-crawl");
const btnScanTab = document.getElementById("btn-scan-tab");

const badgePageTrack = document.getElementById("badge-page-track");
const badgeScannedTrack = document.getElementById("badge-scanned-track");
const liveActivityLog = document.getElementById("live-activity-log");
const logCountIndicator = document.getElementById("log-count-indicator");

const progressContainer = document.getElementById("progress-container");
const progressBarFill = document.getElementById("progress-bar-fill");
const progressPercent = document.getElementById("progress-percent");
const progressMessage = document.getElementById("progress-message");

const statPlCount = document.getElementById("stat-pl-count");
const statFounderCount = document.getElementById("stat-founder-count");
const statLinkedinCount = document.getElementById("stat-linkedin-count");
const resultsCount = document.getElementById("results-count");

const resultsTbody = document.getElementById("results-tbody");
const btnExportCsv = document.getElementById("btn-export-csv");
const btnExportExcel = document.getElementById("btn-export-excel");

// Review & Region Filter Elements
const regionFilter = document.getElementById("region-filter");
const activeRegionFilter = document.getElementById("active-region-filter");
const filterUnder100Crawl = document.getElementById("filter-under-100-crawl");
const btnFilterUnder100 = document.getElementById("btn-filter-under-100");
const under100Badge = document.getElementById("under-100-badge");
const btnFilterUs = document.getElementById("btn-filter-us");
const usBadge = document.getElementById("us-badge");
const btnFilterNonCn = document.getElementById("btn-filter-non-cn");
const nonCnBadge = document.getElementById("non-cn-badge");

let filterUnder100Active = false;
let filterUsActive = false;
let filterNonCnActive = false;

function parseReviewCount(val) {
  if (val === undefined || val === null) return 0;
  if (typeof val === "number") return val;
  const cleaned = String(val).replace(/,/g, '').trim();
  const kMatch = cleaned.match(/([\d\.]+)k/i);
  if (kMatch) {
    return Math.round(parseFloat(kMatch[1]) * 1000);
  }
  const match = cleaned.match(/(\d+)/);
  return match ? parseInt(match[1], 10) : 0;
}

// Initialize
document.addEventListener("DOMContentLoaded", () => {
  setupEventListeners();
  loadAndRenderHistory();
  checkBackendHealth().then(() => {
    restoreActiveJob();
  });
  healthCheckInterval = setInterval(checkBackendHealth, 3000);
});

function switchTab(tabName) {
  if (tabBtnCrawl) tabBtnCrawl.classList.toggle("active", tabName === "crawl");
  if (tabBtnActive) tabBtnActive.classList.toggle("active", tabName === "active");
  if (tabBtnHistory) tabBtnHistory.classList.toggle("active", tabName === "history");

  if (tabCrawl) tabCrawl.classList.toggle("active", tabName === "crawl");
  if (tabActive) tabActive.classList.toggle("active", tabName === "active");
  if (tabHistory) tabHistory.classList.toggle("active", tabName === "history");

  if (tabName === "history") {
    loadAndRenderHistory();
  }
}

function setupEventListeners() {
  if (btnRetryBackend) {
    btnRetryBackend.addEventListener("click", () => {
      backendStatus.className = "status-badge checking";
      backendStatus.innerHTML = `<span class="dot"></span><span class="status-text">Checking...</span>`;
      checkBackendHealth();
    });
  }

  // Page count slider
  if (pageCountInput) {
    pageCountInput.addEventListener("input", (e) => {
      pageValSpan.innerText = e.target.value;
    });
  }

  // Tab switching
  if (tabBtnCrawl) tabBtnCrawl.addEventListener("click", () => switchTab("crawl"));
  if (tabBtnActive) tabBtnActive.addEventListener("click", () => switchTab("active"));
  if (tabBtnHistory) tabBtnHistory.addEventListener("click", () => switchTab("history"));

  // Start deep crawl
  if (btnStartCrawl) btnStartCrawl.addEventListener("click", startDeepCrawl);

  // Stop crawl
  if (btnStopCrawl) {
    btnStopCrawl.addEventListener("click", stopDeepCrawl);
  }

  // Scan active tab
  if (btnScanTab) btnScanTab.addEventListener("click", scanActiveAmazonTab);

  // Export buttons
  if (btnExportCsv) btnExportCsv.addEventListener("click", () => triggerExport("csv"));
  if (btnExportExcel) btnExportExcel.addEventListener("click", () => triggerExport("xlsx"));

  // Review under-100 filter toggle
  if (btnFilterUnder100) {
    btnFilterUnder100.addEventListener("click", () => {
      filterUnder100Active = !filterUnder100Active;
      btnFilterUnder100.classList.toggle("active", filterUnder100Active);
      renderResults(extractedRecords);
    });
  }

  // Region filter toggles
  if (btnFilterUs) {
    btnFilterUs.addEventListener("click", () => {
      filterUsActive = !filterUsActive;
      if (filterUsActive) {
        filterNonCnActive = false;
        if (btnFilterNonCn) btnFilterNonCn.classList.remove("active");
      }
      btnFilterUs.classList.toggle("active", filterUsActive);
      renderResults(extractedRecords);
    });
  }

  if (btnFilterNonCn) {
    btnFilterNonCn.addEventListener("click", () => {
      filterNonCnActive = !filterNonCnActive;
      if (filterNonCnActive) {
        filterUsActive = false;
        if (btnFilterUs) btnFilterUs.classList.remove("active");
      }
      btnFilterNonCn.classList.toggle("active", filterNonCnActive);
      renderResults(extractedRecords);
    });
  }

  // History global actions
  if (btnHistLoadAll) btnHistLoadAll.addEventListener("click", loadAllHistoryIntoTable);
  if (btnHistExportCsv) btnHistExportCsv.addEventListener("click", () => exportAllHistory("csv"));
  if (btnHistExportExcel) btnHistExportExcel.addEventListener("click", () => exportAllHistory("xlsx"));
  if (btnHistClearAll) btnHistClearAll.addEventListener("click", clearAllHistory);

  if (historyFilterInput) {
    historyFilterInput.addEventListener("input", (e) => {
      renderHistoryList(cachedHistory, e.target.value);
    });
  }

  if (historyList) {
    historyList.addEventListener("click", handleHistoryListClick);
  }
}

// Health check for Python backend with multi-host fallback
async function checkBackendHealth() {
  for (const url of CANDIDATE_URLS) {
    try {
      const res = await fetch(`${url}/api/health`, { method: "GET" });
      if (res.ok) {
        BACKEND_URL = url;
        backendStatus.className = "status-badge online";
        backendStatus.innerHTML = `<span class="dot"></span><span class="status-text">Backend Online</span>`;
        backendWarning.classList.add("hidden");
        btnStartCrawl.disabled = false;
        btnScanTab.disabled = false;
        return true;
      }
    } catch (err) {
      // Try next
    }
  }

  setBackendOffline();
  return false;
}

function setBackendOffline() {
  backendStatus.className = "status-badge offline";
  backendStatus.innerHTML = `<span class="dot"></span><span class="status-text">Backend Offline</span>`;
  backendWarning.classList.remove("hidden");
  btnStartCrawl.disabled = true;
  btnScanTab.disabled = true;
}

// Check and resume active job if popup was closed
function restoreActiveJob() {
  chrome.storage.local.get(["activeJobId", "maxPages", "searchQueryVal"], (data) => {
    if (data.activeJobId) {
      currentJobId = data.activeJobId;
      const maxPages = data.maxPages || 3;
      if (data.searchQueryVal) {
        searchQuery.value = data.searchQueryVal;
      }
      pollJobStatus(currentJobId, maxPages);
    }
  });
}

// 1. Deep Crawler Action
async function startDeepCrawl() {
  if (pollInterval) {
    clearInterval(pollInterval);
    pollInterval = null;
  }
  currentJobId = null;

  const query = searchQuery.value.trim();
  if (!query) {
    alert("Please enter an Amazon search keyword or category URL.");
    searchQuery.focus();
    return;
  }

  const marketplace = marketplaceSelect.value;
  const maxPages = parseInt(pageCountInput.value, 10) || 3;
  const maxReviews = filterUnder100Crawl && filterUnder100Crawl.checked ? 100 : null;

  if (filterUnder100Crawl && filterUnder100Crawl.checked) {
    filterUnder100Active = true;
    if (btnFilterUnder100) btnFilterUnder100.classList.add("active");
  }

  btnStartCrawl.disabled = true;
  btnStartCrawl.innerHTML = `<span class="btn-icon">⏳</span> Crawling...`;
  if (btnStopCrawl) btnStopCrawl.classList.remove("hidden");
  showProgress("Initializing multi-page crawler...", 5);
  clearResultsTable();

  const regionVal = regionFilter ? regionFilter.value : "ALL";

  try {
    const response = await fetch(`${BACKEND_URL}/api/extract`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: query,
        marketplace: marketplace,
        max_pages: maxPages,
        max_reviews: maxReviews,
        region_filter: regionVal
      })
    });

    if (!response.ok) {
      throw new Error(`Server returned ${response.status}`);
    }

    const data = await response.json();
    currentJobId = data.job_id;

    // Save job state to storage
    chrome.storage.local.set({
      activeJobId: currentJobId,
      maxPages: maxPages,
      searchQueryVal: query
    });

    // Start polling job status
    pollJobStatus(currentJobId, maxPages);

  } catch (err) {
    alert("Failed to start extraction: " + err.message);
    btnStartCrawl.disabled = false;
    btnStartCrawl.innerHTML = `<span class="btn-icon">🚀</span> Start PL Extraction`;
    if (btnStopCrawl) btnStopCrawl.classList.add("hidden");
    hideProgress();
  }
}

async function stopDeepCrawl() {
  if (!currentJobId) return;
  if (btnStopCrawl) {
    btnStopCrawl.disabled = true;
    btnStopCrawl.innerText = "Stopping...";
  }
  progressMessage.innerText = "Halting search process and saving collected results...";
  try {
    await fetch(`${BACKEND_URL}/api/job/${currentJobId}/stop`, { method: "POST" });
    chrome.storage.local.remove(["activeJobId"]);
  } catch (e) {
    console.error("Stop error:", e);
  }
}

function pollJobStatus(jobId, maxPages) {
  if (pollInterval) clearInterval(pollInterval);
  if (btnStopCrawl) {
    btnStopCrawl.disabled = false;
    btnStopCrawl.innerText = "⏹️ Stop";
    btnStopCrawl.classList.remove("hidden");
  }
  btnStartCrawl.disabled = true;
  btnStartCrawl.innerHTML = `<span class="btn-icon">⏳</span> Crawling...`;

  pollInterval = setInterval(async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/job/${jobId}`);
      if (!res.ok) return;

      const job = await res.json();
      const records = job.records || [];
      extractedRecords = records;

      // Update progress badges
      const currentPage = job.current_page || 1;
      const maxP = job.max_pages || maxPages;
      const scannedCount = job.total_scanned || 0;
      const progressPercentVal = Math.min(Math.round((currentPage / maxP) * 100), 95);

      if (badgePageTrack) badgePageTrack.innerText = `Page ${currentPage} of ${maxP}`;
      if (badgeScannedTrack) badgeScannedTrack.innerText = `${scannedCount} Scanned`;

      showProgress(job.current_message || `Crawling page ${currentPage} of ${maxP}...`, progressPercentVal);

      // Render activity log feed
      if (job.activity_log && liveActivityLog) {
        if (logCountIndicator) logCountIndicator.innerText = `${job.activity_log.length} events`;
        let logHtml = "";
        job.activity_log.forEach((entry) => {
          const isHighlight = entry.includes("Verified PL") || entry.includes("Added PL") || entry.includes("Finished page");
          logHtml += `<div class="log-line ${isHighlight ? 'highlight' : ''}">${escapeHtml(entry)}</div>`;
        });
        liveActivityLog.innerHTML = logHtml;
        liveActivityLog.scrollTop = liveActivityLog.scrollHeight;
      }

      // Render records table
      const isJobRunning = job.status === "running" || job.status === "pending";
      renderResults(records, isJobRunning);

      if (job.status === "completed" || job.status === "failed" || job.status === "stopped") {
        clearInterval(pollInterval);
        chrome.storage.local.remove(["activeJobId"]);
        const finalMsg = job.status === "stopped"
          ? `Stopped by user. Extracted ${records.length} PL brands across ${currentPage} pages.`
          : (job.current_message || "Finished!");
        showProgress(finalMsg, 100);
        btnStartCrawl.disabled = false;
        btnStartCrawl.innerHTML = `<span class="btn-icon">🚀</span> Start PL Extraction`;
        if (btnStopCrawl) {
          btnStopCrawl.disabled = false;
          btnStopCrawl.innerText = "⏹️ Stop";
        }

        // Auto-save completed or stopped search records to persistent history
        if (records && records.length > 0 && !savedJobIds.has(jobId)) {
          savedJobIds.add(jobId);
          saveSearchToHistory({
            type: "deep_crawl",
            query: job.query || (searchQuery ? searchQuery.value.trim() : "") || "Amazon Search",
            marketplace: job.marketplace || (marketplaceSelect ? marketplaceSelect.value : "amazon.com"),
            pages: job.current_page || maxPages,
            records: records
          });
        }
      }
    } catch (e) {
      console.error("Polling error:", e);
    }
  }, 1000);
}

// 2. Quick Scan Active Tab Action
async function scanActiveAmazonTab() {
  btnScanTab.disabled = true;
  btnScanTab.innerHTML = `<span class="btn-icon">⏳</span> Reading Active Tab...`;
  showProgress("Reading products from current Amazon page...", 20);

  try {
    // Query active tab in Chrome
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.url.includes("amazon.")) {
      alert("Please open an Amazon search or category page before running Quick Scan.");
      btnScanTab.disabled = false;
      btnScanTab.innerHTML = `<span class="btn-icon">⚡</span> Extract from Active Tab`;
      hideProgress();
      return;
    }

    // Execute script to scrape visible products
    chrome.tabs.sendMessage(tab.id, { action: "scrape_active_page" }, async (response) => {
      if (chrome.runtime.lastError || !response || !response.products || response.products.length === 0) {
        // Fallback: inject content script directly
        chrome.scripting.executeScript({
          target: { tabId: tab.id },
          files: ['content.js']
        }, () => {
          setTimeout(() => executeActiveScan(tab), 500);
        });
      } else {
        processActiveTabData(response);
      }
    });

  } catch (err) {
    alert("Error accessing active tab: " + err.message);
    btnScanTab.disabled = false;
    btnScanTab.innerHTML = `<span class="btn-icon">⚡</span> Extract from Active Tab`;
    hideProgress();
  }
}

function executeActiveScan(tab) {
  chrome.tabs.sendMessage(tab.id, { action: "scrape_active_page" }, (response) => {
    if (!response || !response.products) {
      alert("No products found on this page. Make sure you are on an Amazon search result page.");
      btnScanTab.disabled = false;
      btnScanTab.innerHTML = `<span class="btn-icon">⚡</span> Extract from Active Tab`;
      hideProgress();
      return;
    }
    processActiveTabData(response);
  });
}

async function processActiveTabData(data) {
  showProgress(`Found ${data.products.length} products. Checking sellers & LinkedIn...`, 50);

  const maxReviews = filterUnder100Crawl && filterUnder100Crawl.checked ? 100 : null;
  if (filterUnder100Crawl && filterUnder100Crawl.checked) {
    filterUnder100Active = true;
    if (btnFilterUnder100) btnFilterUnder100.classList.add("active");
  }

  const activeRegionVal = activeRegionFilter ? activeRegionFilter.value : "ALL";

  try {
    const res = await fetch(`${BACKEND_URL}/api/analyze-active-tab`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        products: data.products,
        marketplace: data.marketplace || "amazon.com",
        max_reviews: maxReviews,
        region_filter: activeRegionVal
      })
    });

    if (!res.ok) throw new Error("Backend analysis failed");

    const result = await res.json();
    extractedRecords = result.records || [];
    renderResults(extractedRecords);

    // Auto-save active tab scan records to persistent history
    if (extractedRecords.length > 0) {
      saveSearchToHistory({
        type: "active_tab",
        query: `Active Tab (${data.products ? data.products.length : 0} products)`,
        marketplace: data.marketplace || "amazon.com",
        pages: 1,
        records: extractedRecords
      });
    }

    showProgress(`Done! Extracted ${extractedRecords.length} unique PL brands.`, 100);
    setTimeout(hideProgress, 3000);

  } catch (err) {
    alert("Analysis failed: " + err.message);
    hideProgress();
  } finally {
    btnScanTab.disabled = false;
    btnScanTab.innerHTML = `<span class="btn-icon">⚡</span> Extract from Active Tab`;
  }
}

// Render Results Table & Metrics
function renderResults(records, isRunning = false) {
  const allRecords = records || [];
  const under100Count = allRecords.filter(r => parseReviewCount(r.reviews) < 100).length;
  const usCount = allRecords.filter(r => (r.seller_country || '').toUpperCase() === 'US').length;
  const nonCnCount = allRecords.filter(r => !['CN', 'HK', 'UNKNOWN', ''].includes((r.seller_country || '').toUpperCase())).length;

  if (under100Badge) under100Badge.innerText = under100Count;
  if (usBadge) usBadge.innerText = usCount;
  if (nonCnBadge) nonCnBadge.innerText = nonCnCount;

  let displayRecords = [...allRecords];
  if (filterUnder100Active) {
    displayRecords = displayRecords.filter(r => parseReviewCount(r.reviews) < 100);
  }
  if (filterUsActive) {
    displayRecords = displayRecords.filter(r => (r.seller_country || '').toUpperCase() === 'US');
  } else if (filterNonCnActive) {
    displayRecords = displayRecords.filter(r => !['CN', 'HK', 'UNKNOWN', ''].includes((r.seller_country || '').toUpperCase()));
  }

  const isFiltered = filterUnder100Active || filterUsActive || filterNonCnActive;
  resultsCount.innerText = isFiltered
    ? `${displayRecords.length} of ${allRecords.length}`
    : `${allRecords.length}`;
  statPlCount.innerText = displayRecords.length;

  let foundersFound = 0;
  let linkedinFound = 0;

  if (displayRecords.length === 0) {
    let emptyMsg = "";
    if (isRunning) {
      emptyMsg = "⏳ Scanning Amazon products and verifying private label sellers...";
    } else if (isFiltered && allRecords.length > 0) {
      emptyMsg = `No brands matching active filters found out of ${allRecords.length} extracted brands.`;
    } else {
      emptyMsg = "No Private Label brands found matching filters on these pages.";
    }

    resultsTbody.innerHTML = `
      <tr class="empty-row">
        <td colspan="12">${emptyMsg}</td>
      </tr>
    `;
    btnExportCsv.disabled = allRecords.length === 0;
    btnExportExcel.disabled = allRecords.length === 0;
    return;
  }

  btnExportCsv.disabled = false;
  btnExportExcel.disabled = false;

  let html = "";
  displayRecords.forEach((r) => {
    const hasFounder = r.founder_name && r.founder_name !== "Not Found";
    const hasLinkedin = r.linkedin_url && r.linkedin_url !== "Not Found";
    const hasWebsite = r.website && r.website !== "Not Found";
    const hasEmail = r.email && r.email !== "Not Found";
    const hasPhone = r.phone && r.phone !== "Not Found";

    if (hasFounder) foundersFound++;
    if (hasLinkedin) linkedinFound++;

    const linkedinBadge = hasLinkedin
      ? `<a href="${r.linkedin_url}" target="_blank" class="linkedin-link">🔗 Profile</a>`
      : `<span style="color:#94a3b8">Not Found</span>`;

    const websiteBadge = hasWebsite
      ? `<a href="${r.website}" target="_blank" style="color:#38bdf8;text-decoration:none;font-weight:600;" title="${r.website}">🌐 Visit</a>`
      : `<span style="color:#64748b">-</span>`;

    const emailBadge = hasEmail
      ? `<a href="mailto:${r.email}" style="color:#fbbf24;text-decoration:none;" title="${r.email}">✉️ ${escapeHtml(r.email)}</a>`
      : `<span style="color:#64748b">-</span>`;

    const phoneBadge = hasPhone
      ? `<span style="color:#a78bfa;" title="${r.phone}">📞 ${escapeHtml(r.phone)}</span>`
      : `<span style="color:#64748b">-</span>`;

    const confClass = (r.pl_confidence || "").toLowerCase() === "high" ? "high" : "medium";

    const revCount = parseReviewCount(r.reviews);
    let revBadge = "";
    if (revCount === 0) {
      revBadge = `<span class="review-badge zero" title="0 reviews or unrated">0 revs</span>`;
    } else if (revCount < 100) {
      revBadge = `<span class="review-badge low" title="Low competition: ${revCount} reviews">🔥 ${revCount}</span>`;
    } else {
      revBadge = `<span class="review-badge high" title="${revCount} reviews">${revCount.toLocaleString()}</span>`;
    }

    const sellerCountry = r.seller_country || "US";
    const sellerLegal = (r.seller_business_name && r.seller_business_name !== "Not Available") ? r.seller_business_name : (r.matched_seller || "-");
    const sellerAddress = (r.seller_address && r.seller_address !== "Not Available") ? r.seller_address : "";

    html += `
      <tr>
        <td><b><a href="${r.product_url}" target="_blank" style="color:#38bdf8;text-decoration:none">${r.asin}</a></b></td>
        <td><b style="color:#f8fafc">${escapeHtml(r.brand_name)}</b></td>
        <td title="Buy Box: ${escapeHtml(r.buybox_seller || '')} | Matched: ${escapeHtml(r.matched_seller || '')}">
          <span style="color:#fbbf24;font-weight:600">${escapeHtml(r.matched_seller || r.buybox_seller || "Single Seller")}</span>
        </td>
        <td><span style="display:inline-block;padding:2px 6px;border-radius:4px;font-size:11px;background:rgba(59,130,246,0.15);color:#93c5fd;font-weight:600;">📍 ${escapeHtml(sellerCountry)}</span></td>
        <td title="${escapeHtml(sellerAddress)}"><span style="font-size:11px;color:#cbd5e1">${escapeHtml(sellerLegal)}</span></td>
        <td>${revBadge}</td>
        <td>${websiteBadge}</td>
        <td>${emailBadge}</td>
        <td>${phoneBadge}</td>
        <td>${escapeHtml(r.founder_name || "Not Found")}</td>
        <td>${linkedinBadge}</td>
        <td><span class="badge ${confClass}">${r.pl_confidence || "PL"}</span></td>
      </tr>
    `;
  });

  resultsTbody.innerHTML = html;
  statFounderCount.innerText = foundersFound;
  statLinkedinCount.innerText = linkedinFound;
}

function clearResultsTable() {
  extractedRecords = [];
  resultsTbody.innerHTML = `
    <tr class="empty-row">
      <td colspan="12">Hunting for Private Label brands...</td>
    </tr>
  `;
  statPlCount.innerText = "0";
  statFounderCount.innerText = "0";
  statLinkedinCount.innerText = "0";
  resultsCount.innerText = "0";
  if (under100Badge) under100Badge.innerText = "0";
  if (usBadge) usBadge.innerText = "0";
  if (nonCnBadge) nonCnBadge.innerText = "0";
  btnExportCsv.disabled = true;
  btnExportExcel.disabled = true;
}

// Progress helpers
function showProgress(message, percent) {
  progressContainer.classList.remove("hidden");
  progressBarFill.style.width = `${percent}%`;
  progressPercent.innerText = `${percent}%`;
  progressMessage.innerText = message;
}

function hideProgress() {
  progressContainer.classList.add("hidden");
}

// Export Trigger
async function triggerExport(fmt) {
  const recordsToExport = filterUnder100Active
    ? (extractedRecords || []).filter(r => parseReviewCount(r.reviews) < 100)
    : (extractedRecords || []);

  if (recordsToExport.length === 0) {
    alert("No records match the current filter to export.");
    return;
  }

  // If no filter is active and we have a current job ID from crawler, use server export endpoint
  if (currentJobId && !filterUnder100Active) {
    const downloadUrl = `${BACKEND_URL}/api/export/${currentJobId}/${fmt}`;
    chrome.tabs.create({ url: downloadUrl });
    return;
  }

  // Filtered or active tab: direct POST export
  try {
    const res = await fetch(`${BACKEND_URL}/api/export-direct/${fmt}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(recordsToExport)
    });

    if (!res.ok) throw new Error("Export failed on server");

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `amazon_pl_export_${Date.now()}.${fmt}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch (err) {
    alert("Export error: " + err.message);
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ==========================================
// SEARCH & EXTRACTION HISTORY MANAGEMENT
// Stores fetched/searched data until cleared
// ==========================================

function formatHistoryDate(date) {
  const d = new Date(date);
  const now = new Date();
  const isToday = d.toDateString() === now.toDateString();
  const timeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  if (isToday) {
    return `Today, ${timeStr}`;
  }
  const dateStr = d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  return `${dateStr}, ${timeStr}`;
}

function updateHistoryBadge(count) {
  if (!historyBadge) return;
  if (count > 0) {
    historyBadge.innerText = count;
    historyBadge.classList.remove("hidden");
  } else {
    historyBadge.innerText = "0";
    historyBadge.classList.add("hidden");
  }
}

function saveSearchToHistory(entry) {
  chrome.storage.local.get(["pl_search_history"], (data) => {
    let history = data.pl_search_history || [];
    const newSession = {
      id: "hist_" + Date.now() + "_" + Math.random().toString(36).substr(2, 4),
      timestamp: Date.now(),
      formattedDate: formatHistoryDate(new Date()),
      type: entry.type,
      query: entry.query,
      marketplace: entry.marketplace,
      pages: entry.pages,
      records: entry.records,
      brandCount: entry.records.length,
      under100Count: entry.records.filter(r => parseReviewCount(r.reviews) < 100).length,
      websiteCount: entry.records.filter(r => r.website && r.website !== "Not Found").length,
      emailCount: entry.records.filter(r => r.email && r.email !== "Not Found").length,
      phoneCount: entry.records.filter(r => r.phone && r.phone !== "Not Found").length,
      founderCount: entry.records.filter(r => r.founder_name && r.founder_name !== "Not Found").length,
      linkedinCount: entry.records.filter(r => r.linkedin_url && r.linkedin_url !== "Not Found").length
    };

    history.unshift(newSession);
    if (history.length > 100) history = history.slice(0, 100);

    cachedHistory = history;
    chrome.storage.local.set({ pl_search_history: history }, () => {
      updateHistoryBadge(history.length);
      if (tabHistory && tabHistory.classList.contains("active")) {
        renderHistoryList(history, historyFilterInput ? historyFilterInput.value : "");
      }
    });
  });
}

function loadAndRenderHistory() {
  chrome.storage.local.get(["pl_search_history"], (data) => {
    cachedHistory = data.pl_search_history || [];
    updateHistoryBadge(cachedHistory.length);
    if (tabHistory && tabHistory.classList.contains("active")) {
      renderHistoryList(cachedHistory, historyFilterInput ? historyFilterInput.value : "");
    }
  });
}

function renderHistoryList(history, filterText = "") {
  if (!historyList) return;

  const q = filterText.toLowerCase().trim();
  const filtered = q
    ? history.filter(item => {
        if (item.query && item.query.toLowerCase().includes(q)) return true;
        if (item.marketplace && item.marketplace.toLowerCase().includes(q)) return true;
        if (item.records && item.records.some(r => r.brand_name && r.brand_name.toLowerCase().includes(q))) return true;
        if (item.records && item.records.some(r => (r.matched_seller || r.buybox_seller || "").toLowerCase().includes(q))) return true;
        if (item.records && item.records.some(r => (r.founder_name || "").toLowerCase().includes(q))) return true;
        return false;
      })
    : history;

  // Update Summary Stats
  const totalSearches = history.length;
  const allBrandsSet = new Set();
  let totalFounders = 0;

  history.forEach(item => {
    (item.records || []).forEach(r => {
      if (r.brand_name) allBrandsSet.add(r.brand_name.toLowerCase().trim());
      if (r.founder_name && r.founder_name !== "Not Found") totalFounders++;
    });
  });

  if (histStatSearches) histStatSearches.innerText = totalSearches;
  if (histStatBrands) histStatBrands.innerText = allBrandsSet.size;
  if (histStatFounders) histStatFounders.innerText = totalFounders;

  // Enable/disable global buttons
  const hasHistory = history.length > 0;
  if (btnHistLoadAll) btnHistLoadAll.disabled = !hasHistory;
  if (btnHistExportCsv) btnHistExportCsv.disabled = !hasHistory;
  if (btnHistExportExcel) btnHistExportExcel.disabled = !hasHistory;
  if (btnHistClearAll) btnHistClearAll.disabled = !hasHistory;

  if (filtered.length === 0) {
    if (q) {
      historyList.innerHTML = `
        <div class="history-empty">
          No saved searches matching "<b>${escapeHtml(q)}</b>".
        </div>
      `;
    } else {
      historyList.innerHTML = `
        <div class="history-empty">
          No search history saved yet.<br>All completed searches will be automatically stored here until cleared!
        </div>
      `;
    }
    return;
  }

  let html = "";
  filtered.forEach(item => {
    const isDeep = item.type === "deep_crawl";
    const typeLabel = isDeep ? "🌐 Deep Search" : "⚡ Active Tab";
    const typeClass = isDeep ? "deep" : "active-tab";

    let brandsPreviewHtml = "";
    (item.records || []).slice(0, 15).forEach(r => {
      const revs = parseReviewCount(r.reviews);
      const revColor = revs < 100 ? "#34d399" : "#94a3b8";
      const founderText = (r.founder_name && r.founder_name !== "Not Found")
        ? `<span class="hist-founder-name">👤 ${escapeHtml(r.founder_name)}</span>`
        : "";
      brandsPreviewHtml += `
        <div class="hist-brand-chip">
          <span class="hist-brand-name">${escapeHtml(r.brand_name)}</span>
          <span style="font-size:9px;color:${revColor};font-weight:600">🔥 ${revs} revs</span>
          <span class="hist-seller-name" title="Seller: ${escapeHtml(r.matched_seller || r.buybox_seller || '')}">${escapeHtml(r.matched_seller || r.buybox_seller || 'PL Seller')}</span>
          ${founderText}
          ${r.website && r.website !== 'Not Found' ? `<span style="font-size:9px;color:#38bdf8;">🌐 Web</span>` : ''}
          ${r.email && r.email !== 'Not Found' ? `<span style="font-size:9px;color:#fbbf24;">✉️ Email</span>` : ''}
        </div>
      `;
    });
    if ((item.records || []).length > 15) {
      brandsPreviewHtml += `<div style="font-size:10px;color:#94a3b8;padding:2px 4px;">+ ${(item.records || []).length - 15} more brands</div>`;
    }

    const under100N = item.under100Count !== undefined ? item.under100Count : (item.records || []).filter(r => parseReviewCount(r.reviews) < 100).length;
    const webCount = item.websiteCount !== undefined ? item.websiteCount : (item.records || []).filter(r => r.website && r.website !== 'Not Found').length;
    const emailCount = item.emailCount !== undefined ? item.emailCount : (item.records || []).filter(r => r.email && r.email !== 'Not Found').length;

    html += `
      <div class="history-item-card" data-id="${item.id}">
        <div class="hist-card-header">
          <div class="hist-card-title-group">
            <span class="hist-type-badge ${typeClass}">${typeLabel}</span>
            <span class="hist-query" title="${escapeHtml(item.query)}">${escapeHtml(item.query || 'Amazon Search')}</span>
            <span class="hist-market-tag">${escapeHtml(item.marketplace || 'amazon.com')}</span>
          </div>
          <span class="hist-timestamp">${item.formattedDate || ''}</span>
        </div>

        <div class="hist-card-stats">
          <span class="hist-stat-chip">🏷️ <b>${item.brandCount || 0}</b> PL Brands</span>
          <span class="hist-stat-chip" style="color:#34d399">🔥 <b>${under100N}</b> (&lt;100 revs)</span>
          <span class="hist-stat-chip" style="color:#38bdf8">🌐 <b>${webCount}</b> Web</span>
          <span class="hist-stat-chip" style="color:#fbbf24">✉️ <b>${emailCount}</b> Email</span>
          <span class="hist-stat-chip">👤 <b>${item.founderCount || 0}</b> Founders</span>
          <span class="hist-stat-chip">🔗 <b>${item.linkedinCount || 0}</b> LinkedIn</span>
          ${item.pages ? `<span class="hist-stat-chip">📄 <b>${item.pages}</b> Pages</span>` : ''}
        </div>

        <div class="hist-card-actions">
          <button class="hist-btn primary-hist-btn btn-load-session" data-id="${item.id}" title="Load these brands into the results table">
            👁️ Load into Table
          </button>
          <button class="hist-btn btn-export-session-csv" data-id="${item.id}" title="Export this search as CSV">
            📄 CSV
          </button>
          <button class="hist-btn btn-export-session-excel" data-id="${item.id}" title="Export this search as Excel">
            📊 Excel
          </button>
          <button class="hist-btn btn-toggle-preview" data-id="${item.id}" title="Preview extracted brands">
            ▾ Preview (${item.brandCount || 0})
          </button>
          <button class="hist-btn delete-hist-btn btn-delete-session" data-id="${item.id}" title="Delete this entry">
            🗑️
          </button>
        </div>

        <div class="hist-preview-drawer hidden" id="preview-${item.id}">
          <div class="hist-preview-list">
            ${brandsPreviewHtml}
          </div>
        </div>
      </div>
    `;
  });

  historyList.innerHTML = html;
}

function handleHistoryListClick(e) {
  const btn = e.target.closest("button");
  if (!btn) return;
  const id = btn.getAttribute("data-id");
  if (!id) return;

  if (btn.classList.contains("btn-load-session")) {
    loadSessionIntoTable(id);
  } else if (btn.classList.contains("btn-export-session-csv")) {
    exportSessionRecords(id, "csv");
  } else if (btn.classList.contains("btn-export-session-excel")) {
    exportSessionRecords(id, "xlsx");
  } else if (btn.classList.contains("btn-toggle-preview")) {
    toggleSessionPreview(id);
  } else if (btn.classList.contains("btn-delete-session")) {
    deleteSessionFromHistory(id);
  }
}

function loadSessionIntoTable(sessionId) {
  const session = cachedHistory.find(h => h.id === sessionId);
  if (!session || !session.records || session.records.length === 0) return;

  currentJobId = null;
  extractedRecords = [...session.records];
  renderResults(extractedRecords);
  showProgress(`Loaded ${extractedRecords.length} brands from '${session.query}' into table.`, 100);
}

function exportSessionRecords(sessionId, fmt) {
  const session = cachedHistory.find(h => h.id === sessionId);
  if (!session || !session.records || session.records.length === 0) return;
  const safeTitle = (session.query || "amazon_pl").replace(/[^a-zA-Z0-9]/g, "_");
  exportDirectData(session.records, fmt, `amazon_pl_${safeTitle}`);
}

function toggleSessionPreview(sessionId) {
  const drawer = document.getElementById(`preview-${sessionId}`);
  if (drawer) {
    drawer.classList.toggle("hidden");
  }
}

function deleteSessionFromHistory(sessionId) {
  cachedHistory = cachedHistory.filter(h => h.id !== sessionId);
  chrome.storage.local.set({ pl_search_history: cachedHistory }, () => {
    updateHistoryBadge(cachedHistory.length);
    renderHistoryList(cachedHistory, historyFilterInput ? historyFilterInput.value : "");
  });
}

function loadAllHistoryIntoTable() {
  if (!cachedHistory || cachedHistory.length === 0) return;

  const seen = new Set();
  const allRecords = [];
  cachedHistory.forEach(s => {
    (s.records || []).forEach(r => {
      const bKey = (r.brand_name || "").toLowerCase().trim();
      if (bKey && !seen.has(bKey)) {
        seen.add(bKey);
        allRecords.push(r);
      }
    });
  });

  if (allRecords.length === 0) {
    alert("No records found in history.");
    return;
  }

  currentJobId = null;
  extractedRecords = allRecords;
  renderResults(extractedRecords);
  showProgress(`Loaded ${allRecords.length} unique brands from all searches into table!`, 100);
}

function exportAllHistory(fmt) {
  if (!cachedHistory || cachedHistory.length === 0) {
    alert("No history to export.");
    return;
  }

  const seen = new Set();
  const allRecords = [];
  cachedHistory.forEach(s => {
    (s.records || []).forEach(r => {
      const bKey = (r.brand_name || "").toLowerCase().trim();
      if (bKey && !seen.has(bKey)) {
        seen.add(bKey);
        allRecords.push(r);
      }
    });
  });

  if (allRecords.length === 0) {
    alert("No records found in history.");
    return;
  }

  exportDirectData(allRecords, fmt, `all_history_amazon_pl_${Date.now()}`);
}

function clearAllHistory() {
  if (!cachedHistory || cachedHistory.length === 0) return;
  if (!confirm("Are you sure you want to clear all stored search history? This cannot be undone.")) return;

  cachedHistory = [];
  chrome.storage.local.remove(["pl_search_history"], () => {
    updateHistoryBadge(0);
    renderHistoryList([], "");
    if (historyFilterInput) historyFilterInput.value = "";
    showProgress("Search history cleared.", 100);
    setTimeout(hideProgress, 2500);
  });
}

async function exportDirectData(records, fmt, filenamePrefix = "amazon_pl_export") {
  try {
    const res = await fetch(`${BACKEND_URL}/api/export-direct/${fmt}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(records)
    });

    if (!res.ok) throw new Error("Export failed on server");

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${filenamePrefix}.${fmt}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch (err) {
    alert("Export error: " + err.message);
  }
}
