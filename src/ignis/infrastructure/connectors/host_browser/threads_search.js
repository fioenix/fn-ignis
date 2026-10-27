({query_id, query, result_limit}) => {
  const page = new URL(location.href), captured_at = new Date().toISOString();
  const answer = {query_id, query, page_url: page.href, captured_at, search_verified: false,
                  empty_state_visible: false, status: 'DEGRADED', records: [], locale: 'en'};
  if (page.origin !== 'https://www.threads.com' || page.pathname !== '/search' || page.hash ||
      [...page.searchParams.keys()].join(',') !== 'q' || page.searchParams.get('q') !== query ||
      !Number.isInteger(result_limit) || result_limit < 1 || result_limit > 100) return answer;
  if (!/^en(?:-|$)/i.test(document.documentElement.lang || '')) { answer.locale = 'unsupported'; return answer; }
  answer.search_verified = true;
  const visible = node => node.getClientRects().length && !node.closest('[hidden]');
  const post = href => { const url = new URL(href, page.origin);
    const match = url.pathname.match(/^\/@[A-Za-z0-9_.]+\/post\/([A-Za-z0-9_-]+)(?:\/media)?\/?$/);
    return url.origin === page.origin && !url.search && !url.hash && match ? {id: match[1], url: url.origin + url.pathname.replace(/\/media\/?$/, '')} : null; };
  // Locale-dependent UI titles match G2's observed English action controls verbatim.
  const titles = ['Like', 'Reply', 'Repost', 'Share'], kinds = ['likes', 'replies', 'reposts', 'shares'];
  const actions = card => Array.from(card.querySelectorAll('svg title'));
  const complete = card => titles.every(label => actions(card).some(node => node.textContent.trim() === label));
  const candidates = [], blocked = [];
  for (const anchor of document.querySelectorAll('a[href]')) {
    if (!anchor.querySelector('time[datetime]') || !post(anchor.href) || !visible(anchor) ||
        anchor.closest('aside,nav,header,[role="complementary"],[role="navigation"]')) continue;
    let card = anchor.parentElement;
    while (card && !complete(card)) card = card.parentElement;
    if (!card) continue;
    const timestamps = card.querySelectorAll('time[datetime]');
    if (timestamps.length !== 1) { blocked.push(card); continue; }
    candidates.push({anchor, card});
  }
  const text = (node, header = null) => {
    if (node === header) return '';
    if (node.nodeType === 3) return node.nodeValue;
    if (node.nodeType !== 1 || !visible(node)) return '';
    const tag = node.tagName.toLowerCase(), role = node.getAttribute('role');
    if (['img', 'svg', 'time', 'button', 'script', 'style'].includes(tag) || role === 'button' || role === 'img') return '';
    if (tag === 'a') { const href = node.getAttribute('href') || '';
      if (node.querySelector('time[datetime]') || /^\/@/.test(new URL(href, page.origin).pathname) || post(node.href)) return ''; }
    if (tag === 'br') return '\n';
    const body = [...node.childNodes].map(child => text(child, header)).join('');
    return tag === 'div' || tag === 'p' ? body + '\n' : body;
  };
  // Explicit reads share a bounded in-tab sample; no polling, scrolling, storage or fetch.
  const cache = globalThis.__ignisThreadsSamples || (globalThis.__ignisThreadsSamples = new Map());
  for (const [key, value] of cache) if (Date.now() - value.time > 3600000) cache.delete(key);
  if (!cache.has(query_id)) { if (cache.size >= 32) cache.delete(cache.keys().next().value);
    cache.set(query_id, {time: Date.now(), query, rows: new Map()}); }
  const sample = cache.get(query_id);
  if (sample.query !== query) return answer;
  let dropped = blocked.length > 0;
  for (const {anchor, card} of candidates) {
    if (blocked.some(parent => parent.contains(card))) { dropped = true; continue; }
    const identity = post(anchor.href), clock = anchor.querySelector('time[datetime]').getAttribute('datetime');
    if (!/(?:Z|[+-]\d\d:\d\d)$/.test(clock || '') || !Number.isFinite(Date.parse(clock)) || Date.parse(clock) > Date.now()) { dropped = true; continue; }
    let header = anchor.parentElement;
    if (header === card) { dropped = true; continue; }
    // The verified card owns the boundary: header nesting depth is not a stable selector.
    while (header.parentElement && header.parentElement !== card) header = header.parentElement;
    const excerpt = text(card, header).split('\n').map(line => line.trim()).filter(Boolean).join('\n');
    if (!excerpt) { dropped = true; continue; }
    const counters = titles.map((label, index) => {
      const title = actions(card).find(node => node.textContent.trim() === label);
      const control = title.closest('[role="button"],button');
      const raw_display = control ? [...control.childNodes].filter(node => node.nodeType === 3 || node.tagName.toLowerCase() !== 'svg').map(node => node.textContent).join('').trim() : '';
      let value = null, precision = 'unknown';
      if (/^\d+$/.test(raw_display)) { value = Number(raw_display); precision = 'exact'; }
      else if (/^\d+\.\d+K$/.test(raw_display)) { value = Math.round(Number(raw_display.slice(0,-1)) * 1000); precision = 'rounded'; }
      if (!Number.isSafeInteger(value)) { value = null; precision = 'unknown'; }
      return {kind: kinds[index], unit: 'count', raw_display, value, precision};
    });
    // The timestamp URL is transient for self-exclusion; Ignis strips its handle before staging.
    if (!sample.rows.has(identity.id) && sample.rows.size < result_limit) sample.rows.set(identity.id,
      {source_url: identity.url, excerpt, published_at: clock, counters});
  }
  answer.records = [...sample.rows.values()].slice(0, result_limit);
  answer.status = answer.records.length && !dropped ? 'HEALTHY' : 'DEGRADED';
  return answer;
}
