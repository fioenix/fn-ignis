({query_id, query, result_limit, action_labels = {}}) => {
  const page = new URL(location.href), captured_at = new Date().toISOString();
  const answer = {query_id, query, page_url: page.href, captured_at, search_verified: false,
                  empty_state_visible: false, status: 'DEGRADED', records: [], locale: 'unsupported'};
  if (page.origin !== 'https://www.threads.com' || page.pathname !== '/search' || page.hash ||
      [...page.searchParams.keys()].join(',') !== 'q' || page.searchParams.get('q') !== query ||
      !Number.isInteger(result_limit) || result_limit < 1 || result_limit > 100) return answer;
  const language = (document.documentElement.lang || '').trim();
  if (!/^[a-z]{2,8}(?:-[a-z0-9]{1,8})*$/i.test(language)) return answer;
  answer.locale = language.split('-')[0].toLowerCase();
  const labels = action_labels[answer.locale] || {};
  answer.search_verified = true;
  const visible = node => node.getClientRects().length && !node.closest('[hidden]');
  const anchorURL = href => { try { return new URL(href, page.origin); } catch { return null; } };
  const post = href => { const url = anchorURL(href); if (!url) return null;
    const match = url.pathname.match(/^\/@[A-Za-z0-9_.]+\/post\/([A-Za-z0-9_-]+)(?:\/media)?\/?$/);
    return url.origin === page.origin && !url.search && !url.hash && match ? {id: match[1], url: url.origin + url.pathname.replace(/\/media\/?$/, '')} : null; };
  const kinds = ['likes', 'replies', 'reposts', 'shares'];
  const actions = card => Array.from(card.querySelectorAll('svg title'));
  const complete = card => Array.from(card.querySelectorAll('button,[role="button"]'))
    .filter(control => visible(control) && control.querySelector('svg')).length >= 4;
  const candidates = [], blocked = [];
  for (const anchor of document.querySelectorAll('a[href]')) {
    if (!anchor.querySelector('time[datetime]') || !post(anchor.getAttribute('href')) || !visible(anchor) ||
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
      const url = anchorURL(href);
      if (!url || node.querySelector('time[datetime]') || /^\/@/.test(url.pathname) || post(href)) return ''; }
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
    const identity = post(anchor.getAttribute('href')), clock = anchor.querySelector('time[datetime]').getAttribute('datetime');
    if (!/(?:Z|[+-]\d\d:\d\d)$/.test(clock || '') || !Number.isFinite(Date.parse(clock)) || Date.parse(clock) > Date.now()) { dropped = true; continue; }
    let header = anchor.parentElement;
    if (header === card) { dropped = true; continue; }
    // The verified card owns the boundary: header nesting depth is not a stable selector.
    while (header.parentElement && header.parentElement !== card) header = header.parentElement;
    const excerpt = text(card, header).split('\n').map(line => line.trim()).filter(Boolean).join('\n').slice(0, 2000);
    if (!excerpt) { dropped = true; continue; }
    const counters = kinds.map(kind => {
      const label = labels[kind];
      const matches = label ? actions(card).filter(node => node.textContent.trim().toLowerCase() === label.toLowerCase()) : [];
      const title = matches.length === 1 ? matches[0] : null;
      const control = title && title.closest('[role="button"],button');
      const raw_display = control ? [...control.childNodes].filter(node => node.nodeType === 3 || node.tagName.toLowerCase() !== 'svg').map(node => node.textContent).join('').trim() : '';
      let value = null, precision = 'unknown';
      const numeric = label && raw_display.toLowerCase().startsWith(label.toLowerCase()) ? raw_display.slice(label.length).trim() : raw_display;
      if (/^\d+$/.test(numeric)) { value = Number(numeric); precision = 'exact'; }
      else if (/^\d+(?:[.,]\d+)?[KM]$/.test(numeric)) {
        value = Math.round(Number(numeric.slice(0,-1).replace(',', '.')) * (numeric.endsWith('M') ? 1000000 : 1000));
        precision = 'rounded';
      }
      if (!Number.isSafeInteger(value)) { value = null; precision = 'unknown'; }
      return {kind, unit: 'count', raw_display, value, precision};
    });
    // Timestamp URL stays transient for self-exclusion and canonical mission author policy.
    if (!sample.rows.has(identity.id) && sample.rows.size < result_limit) sample.rows.set(identity.id,
      {source_url: identity.url, excerpt, published_at: clock, counters});
  }
  answer.records = [...sample.rows.values()].slice(0, result_limit);
  answer.status = answer.records.length && !dropped ? 'HEALTHY' : 'DEGRADED';
  return answer;
}
