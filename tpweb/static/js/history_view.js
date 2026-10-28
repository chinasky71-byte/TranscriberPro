import { html, useState, useEffect } from '/static/js/lib.js';
import { get, post } from '/static/js/api.js';
import { t } from '/static/js/i18n.js';
import { Confirm } from '/static/js/modals.js';
import { messageBox } from '/static/js/dialogs.js';

// Colonne ordinabili: [chiave per il server, testo dell'intestazione]. L'ordine si calcola sul server sui dati veri (data ISO, secondi, byte),
// non sul testo mostrato.
const COLUMNS = [['name', 'web_hist_name'], ['date', 'web_hist_date'], ['language', 'web_hist_lang'],
  ['duration', 'web_hist_duration'], ['size', 'web_hist_sizecol']];

export function HistoryView({ onCount }) {
  const [q, setQ] = useState('');
  const [data, setData] = useState(null);
  const [sort, setSort] = useState(null);            // null = ordine del file; altrimenti { key, dir: 'asc' | 'desc' }
  const [askClear, setAskClear] = useState(false);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let alive = true;
    (async () => {
      const order = sort ? '&sort=' + sort.key + '&dir=' + sort.dir : '';
      const r = await get('/api/history?q=' + encodeURIComponent(q) + order);
      if (alive && r.ok) { setData(r.data); onCount(r.data.stats.total); }
    })();
    return () => { alive = false; };
  }, [q, sort, reload]);
  const st = data ? data.stats : { total: 0, size_text: '–', time_text: '–' };
  // manda anche nome e data della riga mostrata: se la cronologia e' cambiata nel frattempo (cancellata, nuove voci) il server rifiuta
  // (409) invece di aprire il file di un'altra voce, e la tabella si ricarica
  const open = async (row, what) => {
    const r = await post('/api/history/open', { index: row.index, what, name: String(row.name ?? ''), date: String(row.date ?? '') });
    if (r.status === 409 || r.status === 404) setReload((n) => n + 1);
  };
  // clic sull'intestazione: crescente -> decrescente -> ordine del file
  const clickColumn = (key) => setSort((s) => (!s || s.key !== key ? { key, dir: 'asc' } : s.dir === 'asc' ? { key, dir: 'desc' } : null));
  async function clearAll() {
    setAskClear(false);
    const r = await post('/api/history/clear', { confirm: true });
    if (r.ok) setReload((n) => n + 1);
    else messageBox('warning', t('web_hist_clear_title'), t('web_hist_clear_failed'));
  }
  const header = ([key, label]) => {
    const active = sort && sort.key === key;
    const ariaSort = active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none';
    return html`<th class="sortable" tabIndex="0" role="columnheader" aria-sort=${ariaSort} title=${t('web_hist_sort')} data-testid=${'hist-sort-' + key}
        onClick=${() => clickColumn(key)} onKeyDown=${(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); clickColumn(key); } }}>
      ${t(label)}<span class="sort-arrow" aria-hidden="true">${active ? (sort.dir === 'asc' ? '▲' : '▼') : ''}</span></th>`;
  };
  return html`<section class="panel history" data-testid="history">
    <div class="hist-stats">
      <div class="stat-tile"><div class="stat-value" data-testid="hist-total">${st.total}</div><div class="stat-label">${t('tab_history')}</div></div>
      <div class="stat-tile"><div class="stat-value">${st.size_text}</div><div class="stat-label">${t('web_hist_size')}</div></div>
      <div class="stat-tile"><div class="stat-value">${st.time_text}</div><div class="stat-label">${t('web_hist_time')}</div></div>
    </div>
    <div class="hist-toolbar">
      <input class="search" data-testid="hist-search" placeholder=${t('web_hist_search')} value=${q} onInput=${(e) => setQ(e.target.value)} />
      <button class="btn btn-pill-danger" data-testid="hist-clear" disabled=${!data || !st.total} onClick=${() => setAskClear(true)}>${t('web_hist_clear')}</button>
    </div>
    <table class="hist-table"><thead><tr>${COLUMNS.map(header)}<th></th></tr></thead>
      <tbody>${data && data.rows.map((r) => html`<tr data-index=${r.index}><td class="h-name">${r.name}</td><td>${r.date}</td><td>${r.language}</td>
        <td>${r.duration}</td><td>${r.size}</td><td class="h-actions">
          <button class="btn btn-primary btn-small" disabled=${!r.has_srt} onClick=${() => open(r, 'srt')}>${t('hist_open_srt')}</button>
          <button class="btn btn-primary btn-small" disabled=${!r.has_folder} onClick=${() => open(r, 'folder')}>${t('hist_folder')}</button></td></tr>`)}</tbody></table>
    ${data && !data.rows.length ? html`<div class="fs-empty">${t('web_hist_empty')}</div>` : null}
    ${askClear ? html`<${Confirm} title=${t('web_hist_clear_title')} text=${t('web_hist_clear_text')} onNo=${() => setAskClear(false)} onYes=${clearAll} />` : null}
  </section>`;
}
