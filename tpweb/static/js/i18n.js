// Testi: UNICA fonte il dizionario del server (utils/translations.py), stessa funzione tr() della GUI Qt.
import { get } from '/static/js/api.js';

let texts = {};
let lang = 'it';

export async function loadTexts() {
  const r = await get('/api/i18n');
  if (r.ok) { texts = r.data.texts; lang = r.data.lang; document.documentElement.lang = lang; }
}

/** t('chiave') o t('chiave', {n: 3}) per i segnaposto {n}. Chiave mancante: la chiave stessa (come tr() della GUI). */
export function t(key, params) {
  let s = texts[key];
  if (s === undefined) return key;
  if (params) for (const k of Object.keys(params)) s = s.split('{' + k + '}').join(String(params[k]));
  return s;
}
export const language = () => lang;
