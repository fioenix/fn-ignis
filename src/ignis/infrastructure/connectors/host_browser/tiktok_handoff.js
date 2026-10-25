(extract, queries, relayOrigin) => {
  // Runs in a search tab the relay opened. The answer goes straight to the relay page; the host
  // agent that runs this sees only status and counts, never the records (Spec 012 FR-013).
  const query = new URL(location.href).searchParams.get('q');
  const approved = queries.find(item => item.query === query);
  if (!approved) return {posted: false, reason: 'This tab is not an approved search page'};
  if (!window.opener) return {posted: false, reason: 'This tab was not opened by the relay'};
  const answer = extract({query_id: approved.query_id, query: approved.query, result_limit: approved.result_limit});
  window.opener.postMessage({kind: 'ignis-host-answer', answer}, relayOrigin);
  return {posted: true, status: answer.status, records: answer.records.length};
}
