(extract, queries, relayOrigin, requestId) => {
  const page = new URL(location.href);
  const approved = queries.find(item => item.query === page.searchParams.get('q'));
  if (page.origin !== 'https://www.threads.com' || page.pathname !== '/search' || page.hash ||
      [...page.searchParams.keys()].join(',') !== 'q' || !approved) return {posted: false, reason: 'Unapproved search page'};
  if (!window.opener) return {posted: false, reason: 'Relay opener unavailable'};
  const answer = extract({query_id: approved.query_id, query: approved.query, result_limit: approved.result_limit});
  window.opener.postMessage({kind: 'ignis-host-answer', request_id: requestId, answer}, relayOrigin);
  return {posted: true, status: answer.status, records: answer.records.length};
}
