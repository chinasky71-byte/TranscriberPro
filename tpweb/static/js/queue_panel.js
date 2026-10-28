import { html, useState, useRef, useLayoutEffect } from '/static/js/lib.js';
import { t } from '/static/js/i18n.js';
import { Icon } from '/static/js/icon.js';
import { useStore, setUi, getState, addPaths, addFolder, removePaths, startQueue, stopQueue, clearQueue, setShutdown } from '/static/js/store.js';
import { Confirm, FileBrowser } from '/static/js/modals.js';

const VIDEO_EXTS = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v'];
const FILTERS = [['all', 'seg_all'], ['processing', 'seg_processing'], ['queued', 'seg_queued'], ['completed', 'seg_completed']];
const STATUS_KEY = { queued: 'dl_queued', processing: 'dl_processing', completed: 'dl_completed', failed: 'dl_failed' };

function SegmentedFilter() {
  const counts = useStore((s) => s.queue.counts);
  const filter = useStore((s) => s.ui.filter);
  return html`<div class="segmented" data-testid="filters">
    ${FILTERS.map(([key, label]) => html`<button class=${'seg-btn' + (filter === key ? ' checked' : '')} data-filter=${key}
        onClick=${() => setUi({ filter: key })}>${t(label)} (${counts[key === 'all' ? 'all' : key] || 0})</button>`)}
  </div>`;
}

function FileRow({ row, selected, onClick }) {
  const meta = [];
  if (row.size) meta.push(row.size);
  meta.push(t(STATUS_KEY[row.status] || row.status));
  if (row.status === 'processing' && row.progress > 0) meta.push(row.progress + '%');
  return html`<div class=${'file-row status-' + row.status + (selected ? ' selected' : '')} data-path=${row.path} data-status=${row.status}
      onClick=${onClick} title=${row.path}>
    <span class="dot"></span>
    <div class="file-text">
      <div class="file-name"><${Elide} text=${row.filename} /></div>
      <div class="file-meta"><span class="meta-text">${meta.join(' · ')}</span>${row.ov ? html`<span class="meta-ov">${row.ov}</span>` : null}</div>
    </div>
    ${row.status === 'processing' && row.progress > 0
      ? html`<div class="row-bar"><div class="row-bar-fill" style=${{ width: row.progress + '%' }}></div></div>` : null}
  </div>`;
}

let measureCtx = null;
/** ElideMiddle del delegato Qt: il testo che non sta nella riga perde la parte CENTRALE («inizio…fine.mkv»). In CSS non esiste: si misura
 *  con un canvas (stesso font e peso della riga) e si cerca il massimo numero di caratteri che entra. */
function Elide({ text }) {
  const ref = useRef(null);
  const [shown, setShown] = useState(text);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const fit = () => {
      const w = el.clientWidth;
      if (!w) { setShown(text); return; }
      if (!measureCtx) measureCtx = document.createElement('canvas').getContext('2d');
      const cs = getComputedStyle(el);
      measureCtx.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
      const width = (s) => measureCtx.measureText(s).width;
      if (width(text) <= w) { setShown(text); return; }
      const cut = (n) => text.slice(0, Math.ceil(n / 2)) + '\u2026' + text.slice(text.length - Math.floor(n / 2));
      let lo = 0, hi = text.length - 1;
      while (lo < hi) { const mid = Math.ceil((lo + hi) / 2); if (width(cut(mid)) <= w) lo = mid; else hi = mid - 1; }
      setShown(cut(lo));
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, [text]);
  return html`<span class="elide" ref=${ref} title=${text}>${shown}</span>`;
}

function FileList() {
  const rows = useStore((s) => s.queue.rows);
  const filter = useStore((s) => s.ui.filter);
  const selected = useStore((s) => s.ui.selected);
  const visible = rows.filter((r) => filter === 'all' || r.status === filter);
  const seen = {};
  const keyOf = (r) => { seen[r.path] = (seen[r.path] || 0) + 1; return r.path + '#' + seen[r.path]; };      // stesso file due volte (finito e riaccodato)
  function click(row, e) {
    const ui = getState().ui;
    const paths = visible.map((r) => r.path);
    if (e.shiftKey && ui.anchor && paths.includes(ui.anchor)) {
      const a = paths.indexOf(ui.anchor), b = paths.indexOf(row.path);
      setUi({ selected: paths.slice(Math.min(a, b), Math.max(a, b) + 1) });
    } else if (e.ctrlKey || e.metaKey) {
      setUi({ selected: ui.selected.includes(row.path) ? ui.selected.filter((p) => p !== row.path) : [...ui.selected, row.path], anchor: row.path });
    } else setUi({ selected: [row.path], anchor: row.path });
  }
  function key(e) {
    if (e.key === 'Delete' || e.key === 'Backspace') {
      const waiting = new Set(rows.filter((r) => r.status === 'queued' && r.kind !== 'ocr').map((r) => r.path));
      const del = selected.filter((p) => waiting.has(p));       // solo righe ancora in attesa (come la GUI)
      if (del.length) removePaths(del);
    }
  }
  return html`<div class="file-list" data-testid="file-list" tabindex="0" onKeyDown=${key}>
    ${visible.map((r) => html`<${FileRow} key=${keyOf(r)} row=${r} selected=${selected.includes(r.path)} onClick=${(e) => click(r, e)} />`)}
  </div>`;
}

export function QueuePanel() {
  const running = useStore((s) => s.queue.running);
  const progress = useStore((s) => s.queue.progress);
  const job = useStore((s) => s.job);
  const total = useStore((s) => s.queue.rows.length);
  const [modal, setModal] = useState(null);       // 'files' | 'folder' | 'stop'

  return html`<section class="panel left-panel" data-testid="left-panel">
    <${SegmentedFilter} />
    <${FileList} />
    <div class="btn-row">
      <button class="btn btn-primary" data-testid="add-files" onClick=${() => setModal('files')}><${Icon} name="plus" size=${14} class="ico-muted" />${t('add_files')}</button>
      <button class="btn btn-primary" data-testid="add-folder" onClick=${() => setModal('folder')}><${Icon} name="folder" size=${14} class="ico-muted" />${t('add_folder')}</button>
      <button class="btn btn-primary" data-testid="clear" disabled=${running} onClick=${() => clearQueue()}><${Icon} name="trash" size=${14} class="ico-muted" />${t('clear_queue')}</button>
    </div>
    <div class="scanner-card" data-testid="scanner-card">
      <span class="scanner-title">Library Scanner</span><span class="scanner-state">${t('web_scanner_idle')}</span>
      <span class="status-dot-grey"></span><${Icon} name="chevRight" size=${14} class="ico-muted" />
    </div>
    <div class="btn-row">
      <button class="btn btn-start" data-testid="start" disabled=${running || total === 0} onClick=${() => startQueue()}><${Icon} name="play" size=${15} />${t('start')}</button>
      <button class="btn btn-stop" data-testid="stop" disabled=${!running} onClick=${() => setModal('stop')}><${Icon} name="stop" size=${15} />${t('stop')}</button>
    </div>
    <div class="defaults-row">
      <button class="defaults-summary" title=${t('job_defaults_tip')}>${job.defaults_summary ? t('job_defaults_label', { summary: job.defaults_summary }) : ''}</button>
      <label class="check" title=${t('shutdown_tip')}><input type="checkbox" data-testid="shutdown" checked=${!!job.shutdown_after}
          onChange=${(e) => setShutdown(e.target.checked)} /><span class="box"></span><span>${t('shutdown_checkbox')}</span></label>
    </div>
    <div class="progress-row"><div class="progress" data-testid="progress"><div class="progress-fill" style=${{ width: Math.max(0, progress) + '%' }}></div></div>
      <span class="progress-pct">${progress > 0 ? progress + '%' : ''}</span></div>
    ${modal === 'files' ? html`<${FileBrowser} mode="files" title=${t('select_video_files')} exts=${VIDEO_EXTS}
        onCancel=${() => setModal(null)} onPick=${async (paths) => { setModal(null); await addPaths(paths); }} />` : null}
    ${modal === 'folder' ? html`<${FileBrowser} mode="folder" title=${t('select_folder')}
        onCancel=${() => setModal(null)} onPick=${async ([folder]) => { setModal(null); await addFolder(folder); }} />` : null}
    ${modal === 'stop' ? html`<${Confirm} title=${t('confirm_stop_title')} text=${t('confirm_stop_text')}
        onNo=${() => setModal(null)} onYes=${async () => { setModal(null); await stopQueue(); }} />` : null}
  </section>`;
}
