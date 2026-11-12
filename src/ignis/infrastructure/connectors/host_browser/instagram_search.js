({query_id, query, result_limit}) => {
  const page = new URL(location.href), captured_at = new Date().toISOString();
  const answer = {query_id, query, page_url: page.href, captured_at, search_verified: false,
                  empty_state_visible: false, status: 'DEGRADED', records: [], locale: 'unsupported'};
  if (page.origin !== 'https://www.instagram.com' || page.pathname !== '/explore/search/keyword/' || page.hash ||
      [...page.searchParams.keys()].join(',') !== 'q' || page.searchParams.get('q') !== query ||
      !Number.isInteger(result_limit) || result_limit < 1 || result_limit > 100) return answer;
  const language = (document.documentElement.lang || '').trim();
  if (!/^[a-z]{2,8}(?:-[a-z0-9]{1,8})*$/i.test(language)) return answer;
  answer.locale = language.split('-')[0].toLowerCase();
  // A sign-in form or challenge means the grid is not the signed-in keyword search.
  if (document.querySelector('input[name="password"], form[action*="challenge"], iframe[src*="challenge"]')) return answer;
  answer.search_verified = true;
  const visible = node => node.getClientRects().length && !node.closest('[hidden]');
  const tile = href => { let url; try { url = new URL(href, page.origin); } catch { return null; }
    const match = url.pathname.match(/^\/(?:p|reel)\/([A-Za-z0-9_-]+)\/?$/);
    return url.origin === page.origin && !url.search && !url.hash && match ? {id: match[1], url: url.origin + url.pathname} : null; };
  // The caption is the tile image's alt text; control and format characters never reach the excerpt.
  const clean = value => value.normalize('NFC').replace(/[\p{Cc}\p{Cf}]/gu, ch => ch === '\n' ? '\n' : ' ')
    .split('\n').map(line => line.replace(/\s+/g, ' ').trim()).filter(Boolean).join('\n').slice(0, 2000);
  const rows = new Map();
  for (const anchor of document.querySelectorAll('a[href]')) {
    const identity = tile(anchor.getAttribute('href'));
    if (!identity || !visible(anchor) || anchor.closest('nav,header,aside,[role="navigation"]')) continue;
    const image = anchor.querySelector('img[alt]');
    const excerpt = image ? clean(image.getAttribute('alt') || '') : '';
    if (!excerpt || rows.has(identity.id) || rows.size >= result_limit) continue;
    rows.set(identity.id, {source_url: identity.url, excerpt, published_at: null});
  }
  answer.records = [...rows.values()];
  answer.status = answer.records.length ? 'HEALTHY' : 'DEGRADED';
  return answer;
}
