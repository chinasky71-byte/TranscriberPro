// Stato della pagina = copia di vista di cio' che sa il server. La logica (regole della coda, formattazioni) e' tutta sul server:
// qui si riceve, si mostra e si mandano comandi. Eventi: SSE /events (numerati, con ripresa); a ogni cambio di struttura si rilegge
// /api/queue (poche righe, semplice e sempre coerente); solo avanzamento e dimensioni si applicano sul posto.
import { useState, useEffect } from '/static/js/lib.js';
import { get, post } from '/static/js/api.js';

const EMPTY_QUEUE = { running: false, rows: [], counts: { all: 0, queued: 0, processing: 0, completed: 0, failed: 0 }, remaining: 0,
  completed: 0, errors: 0, progress: 0, steps: null, stats: null, started_at: null };

let state = {
  connected: true,
  queue: EMPTY_QUEUE,
  job: { defaults_summary: '', shutdown_after: false },
  resources: null,
  historyCount: null,
  ui: { filter: 'all', selected: [], anchor: null, tab: 'queue', scannerOpen: false },
  log: [],
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
  setState({ queue: q, ui: selected.length === state.ui.selected.length ? state.ui : { ...state.ui, selected } });
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
      case 'steps': setState({ queue: { ...state.queue, steps: m.d } }); break;
      case 'log': pushLog(m.d); break;
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
function pushLog(text) {
  const log = state.log.length >= LOG_MAX ? state.log.slice(state.log.length - LOG_MAX + 1) : state.log.slice();
  log.push(text);
  setState({ log });
}

export function connect() {
  const es = new EventSource('/events');       // dopo una caduta il browser rimanda da solo Last-Event-ID: ripresa senza buchi
  es.addEventListener('state', (e) => {
    const d = JSON.parse(e.data);
    if (d.state && d.state.queue) applyQueue(d.state.queue);
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
    const r = await get('/api/queue/stats');
    if (r.ok) setState({ queue: { ...state.queue, stats: r.data } });
  }, 1000);
  const tick = async () => {
    const r = await get('/api/resources');
    if (r.ok) setState({ resources: r.data });
  };
  tick();
  setInterval(tick, 1000);
}

// -------------------------------------------------------------------------------------------------------------------- comandi
export const addPaths = (paths) => post('/api/queue/add', { paths, only_files: true });
export async function addFolder(folder) { return post('/api/queue/scan', { folder }); }
export async function removePaths(paths) { for (const p of paths) await post('/api/queue/remove', { path: p }); }
export const startQueue = () => post('/api/queue/start');
export const stopQueue = () => post('/api/queue/stop');
export const clearQueue = () => post('/api/queue/clear');
export async function setShutdown(on) {
  const r = await (await import('/static/js/api.js')).put('/api/settings/job_options', { shutdown_after: on });
  if (r.ok) setState({ job: r.data });
}
