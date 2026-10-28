async (extract, queries, receiverURL, requestId, fragmentKey) => {
  const page = new URL(location.href);
  const approved = queries.find(item => item.query === page.searchParams.get('q'));
  if (page.origin !== 'https://www.threads.com' || page.pathname !== '/search' || page.hash ||
      [...page.searchParams.keys()].join(',') !== 'q' || !approved) return {posted: false, reason: 'Unapproved search page'};
  try {
    const answer = extract({query_id: approved.query_id, query: approved.query, result_limit: approved.result_limit});
    const plain = new TextEncoder().encode(JSON.stringify({kind: 'ignis-host-answer', request_id: requestId, answer}));
    // Bound the base64url fragment (12-byte IV and 16-byte GCM tag included) before encryption.
    const maxFragmentChars = 1000000;
    if (Math.ceil((plain.length + 28) * 4 / 3) > maxFragmentChars) return {posted: false, reason: 'Fragment too large'};
    const rawKey = Uint8Array.from(atob(fragmentKey.replace(/-/g, '+').replace(/_/g, '/')), ch => ch.charCodeAt(0));
    const key = await crypto.subtle.importKey('raw', rawKey, 'AES-GCM', false, ['encrypt']);
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const ciphertext = new Uint8Array(await crypto.subtle.encrypt({name: 'AES-GCM', iv}, key, plain));
    const bytes = new Uint8Array(iv.length + ciphertext.length);
    bytes.set(iv); bytes.set(ciphertext, iv.length);
    let binary = '';
    for (const byte of bytes) binary += String.fromCharCode(byte);
    const fragment = btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    if (fragment.length > maxFragmentChars) return {posted: false, reason: 'Fragment too large'};
    setTimeout(() => location.replace(receiverURL + '#' + fragment), 100);
    return {posted: true, status: answer.status, records: answer.records.length};
  } catch {
    return {posted: false, reason: 'Encrypted handoff unavailable'};
  }
}
