// Content script to scrape products directly from the active Amazon tab DOM
function extractActivePageProducts() {
  const products = [];
  const items = document.querySelectorAll('div[data-asin]:not([data-asin=""])');
  const seenAsins = new Set();

  const BAD_BRAND_WORDS = ['pack', 'ounce', 'oz', 'pick', 'choice', 'prime', 'delivery', 'bought', 'star', 'rating', 'review', 'save', 'deal', 'seller', 'featured', 'sponsored', 'option'];

  items.forEach(item => {
    const asin = item.getAttribute('data-asin');
    if (!asin || asin.length !== 10 || seenAsins.has(asin)) return;

    // Title
    const titleEl = item.querySelector('h2 span, h2 a span, h2');
    const title = titleEl ? titleEl.innerText.trim() : '';
    if (!title) return;

    seenAsins.add(asin);

    // Price
    const priceEl = item.querySelector('.a-price .a-offscreen, .a-price-whole');
    const price = priceEl ? priceEl.innerText.trim() : '';

    // URL
    const linkEl = item.querySelector('h2 a');
    const productUrl = linkEl ? linkEl.href : window.location.origin + '/dp/' + asin;

    // Card brand if genuine
    let brand = '';
    const brandEl = item.querySelector('span.a-size-base-plus.a-color-base, [data-cy="title-recipe"] h2 ~ span');
    if (brandEl) {
      const bText = brandEl.innerText.trim();
      const lower = bText.toLowerCase();
      if (bText.length >= 2 && bText.length < 35 && !bText.includes('$') && !bText.includes('★') && !BAD_BRAND_WORDS.some(w => lower.includes(w))) {
        brand = bText;
      }
    }

    // Reviews count
    let reviews = 0;
    const reviewSelectors = [
      'span.s-underline-text',
      'a[href*="#customerReviews"] span',
      'a[href*="#customerReviews"]',
      'span.a-size-base.s-underline-text'
    ];
    for (const sel of reviewSelectors) {
      const el = item.querySelector(sel);
      if (el) {
        const txt = el.innerText.trim().replace(/,/g, '');
        const match = txt.match(/^(\d+)$/);
        if (match) {
          reviews = parseInt(match[1], 10);
          break;
        }
      }
    }

    products.push({
      asin: asin,
      title: title,
      price: price,
      reviews: reviews,
      product_url: productUrl,
      brand: brand
    });
  });

  return {
    marketplace: window.location.hostname.replace('www.', ''),
    products: products
  };
}

// Listen for messages from popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "scrape_active_page") {
    const data = extractActivePageProducts();
    sendResponse(data);
  }
  return true;
});
