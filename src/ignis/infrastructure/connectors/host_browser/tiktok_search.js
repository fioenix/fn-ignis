arg => {
  const page_url = location.href;
  const matches = new URL(page_url).searchParams.get('q') === arg.query;
  const cards = matches ? [...document.querySelectorAll('div[data-e2e="search_top-item"], div[data-e2e="search_video-item"]')] : [];
  const records = [];
  const seen = new Set();
  const content = value => {
    const text = (value || '').trim().slice(0, 2000);
    return text && !text.split(/\s+/).every(part => /^[\d.,]+[KMB]?$/i.test(part)) ? text : '';
  };
  for (const card of cards) {
    if (!card.getClientRects().length) continue;
    const link = card.querySelector('a[href*="/video/"]');
    if (!link) continue;
    const source = new URL(link.href);
    if (source.origin !== 'https://www.tiktok.com' || !/^\/@[A-Za-z0-9_.]+\/video\/[0-9]+$/.test(source.pathname)) continue;
    const source_url = source.origin + source.pathname;
    if (seen.has(source_url)) continue;
    // Public video tiles expose their content in the linked image's accessible label.
    // Keep attribution verbatim; neither the counter nor the query can supply content.
    const image = [...link.querySelectorAll('img[alt]')].find(image =>
      image.getClientRects().length && content(image.getAttribute('alt')));
    const excerpt = image ? content(image.getAttribute('alt')) : content(card.innerText);
    if (!excerpt) continue;
    seen.add(source_url);
    records.push({source_url, excerpt, published_at: null});
    if (records.length >= arg.result_limit) break;
  }
  return {
    query_id: arg.query_id, query: arg.query, page_url,
    captured_at: new Date().toISOString(),
    search_verified: matches && cards.length > 0,
    empty_state_visible: false,
    status: records.length > 0 ? 'HEALTHY' : 'DEGRADED',
    records
  };
}
