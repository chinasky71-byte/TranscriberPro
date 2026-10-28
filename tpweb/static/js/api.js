// Chiamate al server: stesso indirizzo della pagina, il cookie di sessione e' quello del token.
async function request(method, path, body) {
  const res = await fetch(path, {
    method, credentials: 'same-origin',
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = null;
  try { data = await res.json(); } catch (e) { /* risposta senza corpo */ }
  return { ok: res.ok, status: res.status, data };
}
export const get = (path) => request('GET', path);
export const post = (path, body = {}) => request('POST', path, body);
export const put = (path, body = {}) => request('PUT', path, body);
