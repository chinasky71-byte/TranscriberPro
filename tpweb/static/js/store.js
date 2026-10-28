// Stato della pagina = copia di vista di cio' che sa il server. La logica (regole della coda, formattazioni) e' tutta sul server:
// qui si riceve, si mostra e si mandano comandi. Eventi: SSE /events (numerati, con ripresa); a ogni cambio di struttura si rilegge
// /api/queue (poche righe, semplice e sempre coerente); solo avanzamento e dimensioni si applicano sul posto.
import { useState, useEffect } from '/static/js/lib.js';
import { get, post } from '/static/js/api.js';
import { t } from '/static/js/i18n.js';

const EMPTY_QUEUE = { running: false, rows: [], counts: { all: 0, queued: 0, processing: 0, completed: 0, failed: 0 }, remaining: 0,
  completed: 0, errors: 0, progress: 0, steps: null, stats: null, started_at: null };

let state = {
  connected: true,
  queue: EMPTY_QUEUE,
  job: { defaults_summary: '', shutdown_after: false },
  resources: null,
  historyCount: null,
  ui: { filter: 'all', selected: [], anchor: null, current: null, tab: 'queue', scannerOpen: false, settings: null, tool: null },
  message: null,
  env: {},
  tools: { sync: { status: 'idle', run_id: 0, mode: null, progress: 0, rows_rt: {}, outcome: null, output_path: null, errors: [], log: [], plan: { rows: [], srt_files: [], runnable: 0, summary: { ready: 0, check: 0, nosrt: 0, left: 0 }, dirs: { video_dir: '', srt_dir: '', recursive: false } } },
    glossary: { status: 'idle', log: [], report: null, error: null, gate: null, venv_available: true, phase: '', done: 0, total: 0, msg: '', run_info: null } },
  log: [],                                   // {id, text, kind}: le righe le decide il server (filtro, barre sul posto, colori)
  logOptions: { compact: true, pipeline_open: true },
  diag: { elapsed: '–', errors: '0', model: '–', translator: '–', engine: '–' },
  preview: { path: null, status: 'none', poster_id: null },
  gpu: null,
  clockOffset: 0,                            // orologio del server meno quello del browser (barre stimate dei passi)
  title: '',
};
const listeners = new Set();

export const getState = () => state;
export function setState(patch) {
  state = { ...state, ...patch };
  listeners.forEach((fn) => fn());
}
export function setUi(patch) { setState({ ui: { ...state.ui, ...patch } }); }

/** useStore(s => s.queue.rows): si riesegue solo quando il valore scelto cambia. */
export function useStore(selector) {
  const [, force] = useState(0);
  useEffect(() => {
    let last = selector(state);
    const fn = () => { const v = selector(state); if (v !== last) { last = v; force((n) => n + 1); } };
    listeners.add(fn);
    return () => listeners.delete(fn);
  }, []);
  return selector(state);
}

// ---------------------------------------------------------------------------------------------------------- lettura dal server
let refreshTimer = null;
export function refreshQueue() {
  if (refreshTimer) return;
  refreshTimer = setTimeout(async () => {
    refreshTimer = null;
    const r = await get('/api/queue');
    if (r.ok) applyQueue(r.data);
  }, 60);
}

function applyQueue(q) {
  const paths = new Set(q.rows.map((x) => x.path));
  const selected = state.ui.selected.filter((p) => paths.has(p));
  const prev = state.queue.rows;
  const started = q.rows.find((r) => r.status === 'processing' && prev.some((p) => p.path === r.path && p.status !== 'processing'));
  const ui = { ...state.ui, selected };
  if (ui.current && !paths.has(ui.current)) ui.current = null;
  setState({ queue: { ...q, steps: q.steps || state.queue.steps }, ui });
  if (started) selectRow(started.path, true);        // un file passa in lavorazione: si seleziona e si ricarica la locandina (come la GUI)
  else if (!ui.current && state.preview.status !== 'none' && !q.rows.length) setState({ preview: { path: null, status: 'none', poster_id: null } });
}

/** Seleziona UNA riga e ne mostra l'anteprima. */
export function selectRow(path, force = false) {
  setUi({ selected: [path], anchor: path, current: path });
  loadPreview(path, force);
}
export function selectLast() {
  const rows = state.queue.rows;
  if (rows.length) selectRow(rows[rows.length - 1].path);
}
export async function loadPreview(path, force = false) {
  const r = await post('/api/preview/select', { path, force });
  if (r.ok && !r.data.started && force) { /* gia' in corso: nessun lavoro */ }
  const row = state.queue.rows.find((x) => x.path === path);
  const t = await post('/api/preview/title', { path, filename: row ? row.filename : '' });
  if (t.ok && state.ui.current === path) setState({ title: t.data.title });
}

export async function refreshHistoryCount() {
  const r = await get('/api/history');
  if (r.ok) setState({ historyCount: r.data.stats.total });
}

export async function refreshJob() {
  const r = await get('/api/settings');
  if (r.ok) setState({ job: r.data.job_options });
}

function onMessages(msgs) {
  let structural = false;
  for (const m of msgs) {
    switch (m.k) {
      case 'file_progress': patchRow(m.d.path, { progress: m.d.percent }); break;
      case 'size_ready': patchRow(m.d.path, { size: m.d.size }); break;
      case 'progress': setState({ queue: { ...state.queue, progress: m.d } }); break;
      case 'steps': setState({ queue: { ...state.queue, steps: m.d }, clockOffset: m.d.server_time ? m.d.server_time - Date.now() / 1000 : state.clockOffset }); break;
      case 'log': applyLogOp(m.d); break;
      case 'diag': setState({ diag: m.d }); break;
      case 'log_options': setState({ logOptions: m.d }); break;
      case 'poster_loading': setState({ preview: { path: m.d.path, status: 'loading', poster_id: null } }); break;
      case 'poster_loaded': setState({ preview: { path: m.d.path, status: 'found', poster_id: m.d.poster_id } }); break;
      case 'poster_failed': setState({ preview: { path: m.d.path, status: 'failed', poster_id: null } }); break;
      case 'poster_cleared': setState({ preview: { path: null, status: 'none', poster_id: null } }); break;
      case 'gpu_badge': setState({ gpu: m.d }); break;
      case 'glossary_state': setState({ tools: { ...state.tools, glossary: { ...state.tools.glossary, ...m.d } } }); break;
      case 'glossary_log': setState({ tools: { ...state.tools, glossary: { ...state.tools.glossary, log: [...state.tools.glossary.log, m.d.line].slice(-300) } } }); break;
      case 'sync_state': setState({ tools: { ...state.tools, sync: { ...state.tools.sync, ...m.d } } }); break;
      case 'sync_log': {
        const cur = state.tools.sync.log.slice();
        if (m.d.op === 'update_last' && cur.length) cur[cur.length - 1] = m.d.line;
        else { if (m.d.op === 'replace') cur.splice(m.d.remove_index, 1); cur.push(m.d.line); }
        setState({ tools: { ...state.tools, sync: { ...state.tools.sync, log: cur.slice(-2000) } } });
        break;
      }
      case 'env_line': setState({ env: { ...state.env, [m.d.job]: { ...state.env[m.d.job], running: true, lines: [...((state.env[m.d.job] || {}).lines || []), m.d.line].slice(-50), last_line: m.d.line } } }); break;
      case 'env_done': setState({ env: { ...state.env, [m.d.job]: { ...state.env[m.d.job], running: false, exit_code: m.d.exit_code, last_line: m.d.last_line } } }); break;
      case 'scan_finished': selectLast(); structural = true; break;
      case 'history': refreshHistoryCount(); structural = true; break;
      default: structural = true;
    }
  }
  if (structural) refreshQueue();
}

function patchRow(path, patch) {
  const rows = state.queue.rows;
  let i = -1;                                    // stesso file piu' volte: vale la riga ancora da fare o in lavorazione (l'ultima)
  rows.forEach((r, k) => { if (r.path === path && (r.status === 'queued' || r.status === 'processing')) i = k; });
  if (i < 0) return;
  const next = rows.slice();
  next[i] = { ...rows[i], ...patch };
  setState({ queue: { ...state.queue, rows: next } });
}

const LOG_MAX = 5000;
/** Un'operazione del server sul log: accoda, riscrive l'ultima riga (barra sul posto) o toglie una riga e accoda (barra spostata in fondo). */
function applyLogOp(op) {
  let log = state.log.slice();
  if (op.op === 'update_last' && log.length) log[log.length - 1] = op.line;
  else {
    if (op.op === 'replace') log = log.filter((l) => l.id !== op.remove_id);
    log.push(op.line);
    if (log.length > LOG_MAX) log = log.slice(log.length - LOG_MAX);
  }
  setState({ log });
}

function applyFull(st) {
  if (st.queue) applyQueue(st.queue);
  const patch = {};
  if (st.log) patch.log = st.log;
  if (st.diag) patch.diag = st.diag;
  if (st.log_options) patch.logOptions = st.log_options;
  if (st.preview) patch.preview = st.preview;
  if ('gpu' in st) patch.gpu = st.gpu;
  if (st.tools) patch.tools = { ...state.tools, ...st.tools };
  if (st.queue && st.queue.steps && st.queue.steps.server_time) patch.clockOffset = st.queue.steps.server_time - Date.now() / 1000;
  setState(patch);
}

export function connect() {
  const es = new EventSource('/events');       // dopo una caduta il browser rimanda da solo Last-Event-ID: ripresa senza buchi
  es.addEventListener('state', (e) => {
    const d = JSON.parse(e.data);
    if (d.state) applyFull(d.state);
  });
  es.onmessage = (e) => onMessages(JSON.parse(e.data).msgs);
  es.onopen = () => setState({ connected: true });
  es.onerror = () => setState({ connected: false });
  return es;
}

/** Interrogazioni periodiche: tessere (solo a coda in lavoro) e risorse (sempre, come il monitor della GUI). */
export function startPolling() {
  setInterval(async () => {
    if (!state.queue.running) return;
    const r = await get('/api/queue/live');
    if (r.ok) setState({ queue: { ...state.queue, stats: r.data.stats }, diag: r.data.diag });
  }, 1000);
  const tick = async () => {
    const r = await get('/api/resources');
    if (r.ok) setState({ resources: r.data });
  };
  tick();
  setInterval(tick, 1000);
}

// -------------------------------------------------------------------------------------------------------------------- comandi
export async function addPaths(paths) {
  const r = await post('/api/queue/add', { paths, only_files: true });
  if (r.ok) {
    await new Promise((res) => { refreshQueue(); setTimeout(res, 150); });
    post('/api/queue/sizes', { paths: r.data.added });
    selectLast();
  }
  return r;
}
export const openSettings = (tab) => setUi({ settings: { tab } });
export const closeSettings = () => setUi({ settings: null });
export const addFolder = (folder) => post('/api/queue/scan', { folder });
export const setCompact = (enabled) => post('/api/log/compact', { enabled });
export const setPipelineOpen = (open) => post('/api/log/pipeline-card', { open });
export async function removePaths(paths) { for (const p of paths) await post('/api/queue/remove', { path: p }); }
/** Avvia la coda; se un altro strumento la blocca (OCR, Glossario, Sincronizzazione) mostra lo stesso avviso della GUI. */
export async function startQueue() {
  const r = await post('/api/queue/start');
  if (r.status === 409 && r.data && r.data.text_key) setState({ message: { kind: 'warning', title: t(r.data.title_key), text: t(r.data.text_key) } });
  return r;
}
export const stopQueue = () => post('/api/queue/stop');
export const clearQueue = () => post('/api/queue/clear');
export async function setShutdown(on) {
  const r = await (await import('/static/js/api.js')).put('/api/settings/job_options', { shutdown_after: on });
  if (r.ok) setState({ job: r.data });
}

/** Apre uno strumento (come MainWindow._open_glossary_dialog): a coda in lavoro o con l'altro strumento attivo mostra l'avviso e non apre. */
export async function openTool(tool) {
  const r = await get('/api/queue');                           // lo stato fresco del server: i flag degli strumenti non passano dalle righe
  if (!r.ok) return;
  const q = r.data, tl = r.data.tools || {};
  const warn = (key) => setState({ message: { kind: 'warning', title: t(tool === 'glossary' ? 'tools_glossary' : 'sync_dialog_title'), text: t(key) } });
  if (q.running) return warn(tool === 'glossary' ? 'glossary_blocked_processing' : 'sync_blocked_processing');
  if (tool === 'glossary' && tl.sync && state.tools.glossary.status !== 'running') return warn('glossary_blocked_sync');
  if (tool === 'sync') {
    if (tl.glossary) return warn('sync_blocked_glossary');
  }
  setUi({ tool });
}
export const closeTool = () => setUi({ tool: null });
