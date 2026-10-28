import { html, useState, useEffect } from '/static/js/lib.js';
import { get, post } from '/static/js/api.js';
import { t } from '/static/js/i18n.js';

export function HistoryView({ onCount }) {
  const [q, setQ] = useState('');
  const [data, setData] = useState(null);
  useEffect(() => {
    let alive = true;
    (async () => {
      const r = await get('/api/history?q=' + encodeURIComponent(q));
      if (alive && r.ok) { setData(r.data); onCount(r.data.stats.total); }
    })();
    return () => { alive = false; };
  }, [q]);
  const st = data ? data.stats : { total: 0, size_text: '–', time_text: '–' };
  const open = (index, what) => post('/api/history/open', { index, what });
  return html`<section class="panel history" data-testid="history">
    <div class="hist-stats">
      <div class="stat-tile"><div class="stat-value" data-testid="hist-total">${st.total}</div><div class="stat-label">${t('tab_history')}</div></div>
      <div class="stat-tile"><div class="stat-value">${st.size_text}</div><div class="stat-label">${t('web_hist_size')}</div></div>
      <div class="stat-tile"><div class="stat-value">${st.time_text}</div><div class="stat-label">${t('web_hist_time')}</div></div>
    </div>
    <input class="search" data-testid="hist-search" placeholder=${t('web_hist_search')} value=${q} onInput=${(e) => setQ(e.target.value)} />
    <table class="hist-table"><thead><tr><th>${t('web_hist_name')}</th><th>${t('web_hist_date')}</th><th>${t('web_hist_lang')}</th>
      <th>${t('web_hist_duration')}</th><th>${t('web_hist_sizecol')}</th><th></th></tr></thead>
      <tbody>${data && data.rows.map((r) => html`<tr data-index=${r.index}><td class="h-name">${r.name}</td><td>${r.date}</td><td>${r.language}</td>
        <td>${r.duration}</td><td>${r.size}</td><td class="h-actions">
          <button class="btn btn-primary btn-small" disabled=${!r.has_srt} onClick=${() => open(r.index, 'srt')}>${t('hist_open_srt')}</button>
          <button class="btn btn-primary btn-small" disabled=${!r.has_folder} onClick=${() => open(r.index, 'folder')}>${t('hist_folder')}</button></td></tr>`)}</tbody></table>
    ${data && !data.rows.length ? html`<div class="fs-empty">${t('web_hist_empty')}</div>` : null}
  </section>`;
}
