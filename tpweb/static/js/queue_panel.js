import { html, useState, useRef, useLayoutEffect } from '/static/js/lib.js';
import { t } from '/static/js/i18n.js';
import { ScannerCard } from '/static/js/scanner.js';
import { Icon } from '/static/js/icon.js';
import { useStore, setUi, getState, refreshQueue, loadPreview, addPaths, addFolder, removePaths, startQueue, stopQueue, clearQueue, setShutdown, openSettings } from '/static/js/store.js';
import { Confirm, FileBrowser } from '/static/js/modals.js';
import { ContextMenu } from '/static/js/context_menu.js';
import { get, post } from '/static/js/api.js';

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

function FileRow({ row, selected, onClick, dnd }) {
  const meta = [];
  if (row.size) meta.push(row.size);
  meta.push(t(STATUS_KEY[row.status] || row.status));
  if (row.status === 'processing' && row.progress > 0) meta.push(row.progress + '%');
  const movable = row.status === 'queued' && row.kind !== 'ocr';
  return html`<div class=${'file-row status-' + row.status + (selected ? ' selected' : '') + (dnd.over === row.path ? (dnd.after ? ' drop-after' : ' drop-before') : '')}
      data-path=${row.path} data-status=${row.status} onClick=${onClick} title=${row.path} onContextMenu=${dnd.menu}
      draggable=${movable} onDragStart=${(e) => dnd.start(e, row)} onDragOver=${(e) => dnd.over_(e, row)} onDrop=${(e) => dnd.drop(e, row)}
      onDragEnd=${dnd.end}>
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

let overrideOptions = null;
async function loadOverrideOptions() {
  if (!overrideOptions) { const r = await get('/api/queue/override-options'); if (r.ok) overrideOptions = r.data; }
  return overrideOptions;
}
const isMovable = (r) => r.status === 'queued' && r.kind !== 'ocr';

/** Nuovo ordine dopo un rilascio: stesso algoritmo di ReorderableFileList._handle_drop (la posizione si conta fra le sole righe spostabili). */
export function newOrder(rows, moved, dropRow) {
  const before = rows.filter((r) => r !== moved && isMovable(r));
  const k = before.filter((r) => rows.indexOf(r) < dropRow).length;
  return before.slice(0, k).concat([moved], before.slice(k));
}

function FileList() {
  const rows = useStore((s) => s.queue.rows);
  const filter = useStore((s) => s.ui.filter);
  const selected = useStore((s) => s.ui.selected);
  const overrides = useStore((s) => s.queue.overrides) || {};
  const [menu, setMenu] = useState(null);
  const [dragRow, setDragRow] = useState(null);
  const [over, setOver] = useState({ path: null, after: false });
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
    if (!getState().ui.selected.includes(row.path)) return;
    if (getState().ui.current !== row.path) { setUi({ current: row.path }); loadPreview(row.path); }        // la riga corrente (ultima cliccata) fa da anteprima
  }
  const waitingSelected = (sel) => rows.filter((r) => sel.includes(r.path) && isMovable(r) && visible.includes(r));
  function key(e) {
    if (e.key === 'Delete' || e.key === 'Backspace') {
      const del = waitingSelected(selected).map((r) => r.path);        // solo righe ancora in attesa (come la GUI)
      if (del.length) removePaths(del);
    }
  }

  // ---- riordino: solo una riga alla volta e solo righe in attesa ------------------------------------------------------------
  const dnd = {
    over: over.path, after: over.after,
    start(e, row) {
      if (!isMovable(row) || selected.length > 1) { e.preventDefault(); return; }
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', row.path);
      setDragRow(row);
    },
    over_(e, row) {
      if (!dragRow) return;
      e.preventDefault();
      const r = e.currentTarget.getBoundingClientRect();
      setOver({ path: row.path, after: e.clientY > r.top + r.height / 2 });
    },
    async drop(e, row) {
      e.preventDefault();
      const moved = dragRow;
      const after = over.after;
      setDragRow(null); setOver({ path: null, after: false });
      if (!moved) return;
      const dropRow = rows.indexOf(row) + (after ? 1 : 0);
      const order = newOrder(rows, moved, dropRow);
      const current = rows.filter(isMovable);
      if (order.every((r, i) => r === current[i])) return;
      await post('/api/queue/reorder', { order: order.map((r) => r.path), moved: moved.path });
      refreshQueue();
    },
    end() { setDragRow(null); setOver({ path: null, after: false }); },
    menu: (e) => {},
  };

  // ---- menu contestuale ----------------------------------------------------------------------------------------------------
  async function openMenu(e, row) {
    e.preventDefault();
    let sel = getState().ui.selected;
    if (row && !sel.includes(row.path)) { sel = [row.path]; setUi({ selected: sel, anchor: row.path }); }
    const opts = await loadOverrideOptions();
    const normal = row ? waitingSelected(sel) : [];
    const paths = normal.map((r) => r.path);
    const items = [];
    if (normal.length && opts) {
      const cur = paths.map((p) => overrides[p] || {});
      const common = (k) => { const v = new Set(cur.map((c) => (k in c ? c[k] : null))); return v.size === 1 ? [...v][0] : '__misto__'; };
      const apply = (k, v) => post('/api/queue/overrides', { paths, key: k, value: v });
      const sub = (title, k, entries) => ({ label: title, children: [[t('job_ov_default'), null], ...entries].map(([label, value]) => (
        { label, checked: common(k) === value, onClick: () => apply(k, value) })) });
      const yesNo = [[t('job_ov_yes'), true], [t('job_ov_no'), false]];
      items.push(sub(t('job_ov_lang'), 'target_language', opts.languages.map((c) => [t('lang_name_' + c), c])));
      items.push(sub(t('job_ov_translation'), 'translation_model', [[t('job_ov_nllb'), 'nllb_finetuned'], [t('job_ov_tg'), 'llm']]));
      items.push(sub(t('force_audio_title'), 'force_audio_transcription', yesNo));
      items.push(sub(t('job_ov_gender'), 'gender_correction_enabled', yesNo));
      items.push(sub(t('job_ov_mux'), 'mux_subtitle_into_video', yesNo));
      items.push(sub(t('job_ov_upload'), 'opensubtitles_upload_enabled', yesNo));
      items.push({ separator: true });
      items.push({ label: t('job_ov_reset'), disabled: !cur.some((c) => Object.keys(c).length),
        onClick: async () => { for (const k of opts.keys) await post('/api/queue/overrides', { paths, key: k, value: null }); } });
      items.push({ separator: true });
    }
    const removable = row ? normal.map((r) => r.path) : [];
    items.push({ label: t('remove_from_queue'), disabled: !removable.length, onClick: () => removePaths(removable) });
    setMenu({ x: e.clientX, y: e.clientY, items });
  }
  dnd.menu = (e) => { e.stopPropagation(); };

  return html`<div class="file-list" data-testid="file-list" tabindex="0" onKeyDown=${key} onContextMenu=${(e) => openMenu(e, null)}>
    ${visible.map((r) => html`<${FileRow} key=${keyOf(r)} row=${r} selected=${selected.includes(r.path)} onClick=${(e) => click(r, e)}
        dnd=${{ ...dnd, menu: (e) => { e.stopPropagation(); openMenu(e, r); } }} />`)}
    ${menu ? html`<${ContextMenu} x=${menu.x} y=${menu.y} items=${menu.items} onClose=${() => setMenu(null)} />` : null}
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
    <${ScannerCard} />
    <div class="btn-row">
      <button class="btn btn-start" data-testid="start" disabled=${running || total === 0} onClick=${() => startQueue()}><${Icon} name="play" size=${15} />${t('start')}</button>
      <button class="btn btn-stop" data-testid="stop" disabled=${!running} onClick=${() => setModal('stop')}><${Icon} name="stop" size=${15} />${t('stop')}</button>
    </div>
    <div class="defaults-row">
      <button class="defaults-summary" data-testid="defaults-summary" title=${t('job_defaults_tip')} onClick=${() => openSettings('jobs')}>${job.defaults_summary ? t('job_defaults_label', { summary: job.defaults_summary }) : ''}</button>
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
