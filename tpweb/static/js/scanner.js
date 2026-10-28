import { html, useState, useEffect, useRef, useMemo } from '/static/js/lib.js';
import { t } from '/static/js/i18n.js';
import { get, post, put } from '/static/js/api.js';
import { Icon } from '/static/js/icon.js';
import { useStore } from '/static/js/store.js';
import { messageBox } from '/static/js/dialogs.js';
import { Confirm } from '/static/js/modals.js';

const FORMATS = [[null, 'all_formats'], ['pgs', 'PGS'], ['vobsub', 'VOBSUB'], ['assssa', 'ASS/SSA'], ['nosrt', 'No SRT']];
const EMPTY = { connected: null, error: '', stats_text: '', without: 0, visible: 0, rows: [], import_enabled: false, import_is_ass: false };
const TYPES = [['', 'all_types'], ['movie', 'film_type'], ['tvshow', 'tv_series_type']];
const typeText = (m) => (m === 'movie' ? t('film_type') : m === 'tvshow' ? t('tv_series_type') : m);

/** Card «Library Scanner» (LibraryScannerWidget): elenco dei video senza sottotitoli italiani, filtri, import in coda, conversione ASS/SSA. */
export function ScannerCard() {
  const tick = useStore((s) => s.libraryTick);
  const ocr = useStore((s) => s.ocr);
  const [open, setOpen] = useState(null);                     // null = non ancora letto dal server
  const [enabled, setEnabled] = useState(true);
  const [data, setData] = useState(EMPTY);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [type, setType] = useState('');
  const [days, setDays] = useState(0);
  const [fmt, setFmt] = useState(null);
  const [askSp, setAskSp] = useState(false);
  const [sort, setSort] = useState(null);                     // {col, dir}
  const prevFmt = useRef(null);
  const filters = useRef({});
  filters.current = { search, type, days, fmt };

  async function load() {
    const f = filters.current;
    setLoading(true);
    const q = new URLSearchParams({ search: f.search.trim(), type: f.type, min_days: String(f.days) });
    if (f.fmt) q.set('format', f.fmt);
    const r = await get('/api/library?' + q.toString());
    setLoading(false);
    if (r.ok) setData(r.data);
  }
  async function reapply(nextDays, nextFmt) {
    const q = new URLSearchParams({ min_days: String(nextDays) });
    if (nextFmt) q.set('format', nextFmt);
    const r = await get('/api/library/view?' + q.toString());
    if (r.ok) setData(r.data);
  }
  useEffect(() => {                                           // stato della card e primo caricamento (come la GUI, poco dopo l'avvio)
    get('/api/library/state').then((r) => { if (r.ok) { setOpen(r.data.open); setEnabled(r.data.enabled); } });
    const first = setTimeout(load, 2500);
    return () => clearTimeout(first);
  }, []);
  useEffect(() => { if (tick > 0 && open) load(); }, [tick]);   // il server ha notificato un sottotitolo creato (a card chiusa si aggiorna con il timer)
  useEffect(() => {                                           // aggiornamento automatico ogni 5 minuti, solo a card aperta
    if (!open) return undefined;
    const id = setInterval(load, 5 * 60 * 1000);
    return () => clearInterval(id);
  }, [open]);
  const searchTimer = useRef(null);
  function onSearch(v) {                                      // ricerca sul server dopo 500 ms senza digitare
    setSearch(v);
    clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => { filters.current = { ...filters.current, search: v }; load(); }, 500);
  }
  function onType(v) { setType(v); filters.current = { ...filters.current, type: v }; setTimeout(load, 0); }
  function onDays(v) { const n = Math.max(0, Math.min(9999, parseInt(v, 10) || 0)); setDays(n); reapply(n, fmt); }
  function onFmt(v) {
    const next = v || null;
    const prev = prevFmt.current;
    prevFmt.current = next;
    setFmt(next);
    filters.current = { ...filters.current, fmt: next };
    if (next === 'assssa' || prev === 'assssa') setTimeout(load, 0);                // ASS/SSA e' un altro endpoint: serve ricaricare
    else reapply(days, next);
  }
  function toggle() {
    const next = !open;
    setOpen(next);
    put('/api/library/card', { open: next });
  }
  async function convertAss(ids) {
    const r = await post('/api/library/ass', { video_ids: ids });
    if (r.ok) messageBox(r.data.level === 'information' ? 'info' : 'warning', t(r.data.title_key), r.data.message);
  }
  async function startOcr(row) {
    const r = await post('/api/ocr/start', { path: row.windows_path, kind: row.ocr_kind });
    if (r.status === 409) messageBox('info', t('ocr_section_title'), t('ls_ocr_other_running'));       // un OCR alla volta
  }
  async function superpower() {
    const pre = await post('/api/ocr/superpower/check');
    if (pre.ok && !pre.data.ok) { messageBox(pre.data.level === 'info' ? 'info' : 'warning', t('web_superpower_title'), pre.data.message); return; }
    setAskSp(true);
  }
  async function superpowerGo() {
    setAskSp(false);
    const r = await post('/api/ocr/superpower');
    if (r.ok && r.data.message) messageBox(r.data.level === 'info' ? 'info' : 'warning', t('web_superpower_title'), r.data.message);
  }
  async function importPaths(paths, log) {
    const r = await post('/api/library/import', { paths, log });
    if (r.ok && r.data.added > 0) await reapply(days, fmt);
  }
  function importOne(row) {
    if (row.badge === 'ass' && row.id) convertAss([row.id]);                        // ASS/SSA: conversione sul server, non coda locale
    else importPaths([row.windows_path], false);
  }
  function importAll() {
    if (fmt === 'assssa') { convertAss([]); return; }                               // corpo vuoto: il server converte tutti i pending
    const paths = shown.map((r) => r.windows_path).filter(Boolean);
    if (paths.length) importPaths(paths, true);
  }

  const shown = useMemo(() => {
    let rows = data.rows.filter((r) => !r.hidden);
    if (sort) {
      const key = { 0: 'filename', 1: 'media_type', 2: 'days' }[sort.col];
      rows = rows.slice().sort((a, b) => (key === 'days' ? a.days - b.days : String(a[key]).localeCompare(String(b[key]))) * (sort.dir === 'asc' ? 1 : -1));
    }
    return rows;
  }, [data, sort]);
  const clickSort = (col) => setSort(sort && sort.col === col ? { col, dir: sort.dir === 'asc' ? 'desc' : 'asc' } : { col, dir: 'asc' });
  const arrow = (col) => (sort && sort.col === col ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : '');

  if (!enabled) return null;
  let stats = t('waiting_connection');
  const ocrText = ocr.progress_text;           // durante l'OCR l'avanzamento prende il posto delle statistiche (stessa riga)
  if (loading && !data.rows.length) stats = t('loading');
  else if (data.error === 'config_missing') stats = t('config_missing');
  else if (data.error) stats = t('error_status', { message: data.error });
  else if (data.stats_text) stats = data.stats_text;
  const dot = data.connected === null ? 'grey' : data.connected ? 'on' : 'off';
  const badge = data.connected ? data.visible : (data.without || 0);

  return html`<div class=${'scanner-card' + (open ? ' open' : '')} data-testid="scanner-card" data-open=${String(!!open)}>
    <div class="scanner-head" data-testid="scanner-head" onClick=${toggle}>
      <span class="scanner-title">${t('library_scanner_title')}</span>
      ${badge > 0 ? html`<span class="scanner-badge" data-testid="scanner-badge">${badge}</span>` : null}
      <span class="scanner-state" data-testid="scanner-state">${data.connected ? t('mw_scanner_active') : t('web_scanner_idle')}</span>
      <span class=${'scanner-dot ' + dot} data-testid="scanner-dot"></span>
      <button class="tool-btn small" data-testid="scanner-refresh" title=${t('refresh')} onClick=${(e) => { e.stopPropagation(); load(); }}><${Icon} name="sync" size=${14} /></button>
      <${Icon} name=${open ? 'chevDown' : 'chevRight'} size=${14} class="ico-muted" />
    </div>
    ${open ? html`<div class="scanner-body" data-testid="scanner-body">
      <input class="input" data-testid="scanner-search" placeholder=${t('search_placeholder')} value=${search} onInput=${(e) => onSearch(e.target.value)} />
      <div class="scanner-filters">
        <span>${t('type_filter')}</span>
        <select class="select" data-testid="scanner-type" value=${type} onChange=${(e) => onType(e.target.value)}>${TYPES.map(([v, k]) => html`<option value=${v} selected=${v === type}>${t(k)}</option>`)}</select>
        <span>${t('days_filter')}</span>
        <input class="input days-input" data-testid="scanner-days" value=${days === 0 ? t('all_days') : days}
          onFocus=${(e) => { if (days === 0) e.target.value = ''; }} onChange=${(e) => onDays(e.target.value)} />
        <span>${t('format_filter')}</span>
        <select class="select" data-testid="scanner-format" value=${fmt || ''} onChange=${(e) => onFmt(e.target.value)}>${FORMATS.map(([v, k]) => html`<option value=${v || ''} selected=${(v || '') === (fmt || '')}>${v ? k : t(k)}</option>`)}</select>
      </div>
      <div class="scanner-table-wrap"><table class="scanner-table" data-testid="scanner-table">
        <thead><tr><th onClick=${() => clickSort(0)}>${t('file_col')}${arrow(0)}</th><th class="c-type" onClick=${() => clickSort(1)}>${t('type_col')}${arrow(1)}</th>
          <th class="c-days" onClick=${() => clickSort(2)}>${t('days_col')}${arrow(2)}</th><th class="c-sub">Sub</th><th class="c-add"></th></tr></thead>
        <tbody>${shown.map((r) => html`<tr key=${r.windows_path || r.id} data-path=${r.windows_path}>
          <td class=${'c-file' + (r.audio_ita ? ' audio-ita' : '')} title=${r.audio_ita ? t('ls_audio_ita_tip', { path: r.windows_path }) : r.windows_path}>${r.filename}</td>
          <td class="c-type">${typeText(r.media_type)}</td>
          <td class=${'c-days' + (r.days_class ? ' days-' + r.days_class : '')}>${r.days}</td>
          <td class="c-sub">${r.badge === 'bitmap' ? html`<button class="badge-btn bitmap" data-testid=${'badge-' + r.id} title=${t('ls_bitmap_tip')} data-kind=${r.ocr_kind} onClick=${() => startOcr(r)}>${r.badge_label}</button>`
            : r.badge === 'ass' ? html`<button class=${'badge-btn ass' + (r.ass_done ? ' done' : '')} data-testid=${'badge-' + r.id} disabled=${r.ass_done}
              title=${r.ass_done ? t('ls_ass_done_tip') : t('ls_ass_tip')} onClick=${() => convertAss([r.id])}>ASS</button>` : null}</td>
          <td class="c-add"><button class="add-btn" data-testid=${'add-' + r.id} disabled=${r.queued} title=${r.queued ? t('already_queued') : ''}
            onClick=${() => importOne(r)}>${r.queued ? '✓' : html`<${Icon} name="plus" size=${14} />`}</button></td></tr>`)}</tbody></table></div>
      <div class="btn-row"><button class="btn btn-primary" data-testid="scanner-import-all" disabled=${!shown.length} onClick=${importAll}>${fmt === 'assssa' ? t('ls_convert_ass') : t('import_filtered')}</button>
        <button class="btn btn-primary" data-testid="scanner-superpower" title=${t('ls_superpower_tip')} onClick=${superpower}><${Icon} name="sparkle" size=${14} />Superpower</button></div>
      <div class="scanner-stats" data-testid="scanner-stats">${ocrText || stats}</div>
    </div>` : null}
    ${askSp ? html`<${Confirm} title=${t('web_superpower_confirm_title')} text=${t('ls_sp_confirm')} onNo=${() => setAskSp(false)} onYes=${superpowerGo} />` : null}
  </div>`;
}
