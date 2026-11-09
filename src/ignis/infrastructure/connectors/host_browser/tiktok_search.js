arg => {
  const page_url = location.href;
  const language = (document.documentElement.lang || '').trim();
  const locale = /^[a-z]{2,8}(?:-[a-z0-9]{1,8})*$/i.test(language) ? language.split('-')[0].toLowerCase() : 'unsupported';
  const matches = new URL(page_url).searchParams.get('q') === arg.query;
  const CARD = 'div[data-e2e="search_top-item"], div[data-e2e="search_video-item"]';
  const cards = matches ? [...document.querySelectorAll(CARD)] : [];
  const records = [];
  const seen = new Set();
  const content = value => {
    const text = (value || '').trim();
    // Truncating here could cut the attribution template while retaining the poster's name.
    if (text.length > 2000) return '';
    return text && !text.split(/\s+/).every(part => /^[\d.,]+[KMB]?$/i.test(part)) ? text : '';
  };
  // The poster's name has its own element, so it is removed exactly in any interface language.
  // The earliest occurrence of the name or handle and everything after it go; sound text often
  // repeats the name. A record whose name cannot be tied to this card is dropped, and the name
  // never leaves this function.
  const clean = value => (value || '').normalize('NFC').replace(/\p{Cf}/gu, '').trim();
  const occurrence = (text, value) => {
    if (!value) return -1;
    const pattern = value.split(/\s+/).map(part => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+');
    const found = new RegExp('(?<![\\p{L}\\p{N}])' + pattern + '(?![\\p{L}\\p{N}])', 'iu').exec(text);
    return found ? found.index : -1;
  };
  const beforePoster = (label, card, handle) => {
    const scope = card.parentElement;
    if (!scope || scope.querySelectorAll(CARD).length !== 1) return '';
    const names = [...scope.querySelectorAll('[data-e2e="search-card-user-unique-id"]')];
    if (names.length !== 1 || !names[0].getClientRects().length) return '';
    const text = clean(label);
    const at = occurrence(text, clean(names[0].textContent));
    if (at < 0) return '';
    const handleAt = occurrence(text, handle);
    return text.slice(0, handleAt < 0 ? at : Math.min(at, handleAt)).trim();
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
    const label = image ? content(image.getAttribute('alt')) : '';
    const excerpt = label ? beforePoster(label, card, source.pathname.split('/')[1].slice(1)) : '';
    if (!excerpt) continue;
    seen.add(source_url);
    records.push({source_url, excerpt, published_at: null});
    if (records.length >= arg.result_limit) break;
  }
  return {
    query_id: arg.query_id, query: arg.query, page_url, locale,
    captured_at: new Date().toISOString(),
    search_verified: matches && cards.length > 0,
    empty_state_visible: false,
    status: records.length > 0 ? 'HEALTHY' : 'DEGRADED',
    records
  };
}
