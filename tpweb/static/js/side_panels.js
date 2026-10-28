import { html, useState, useEffect, useRef, useLayoutEffect } from '/static/js/lib.js';
import { t } from '/static/js/i18n.js';
import { Icon } from '/static/js/icon.js';
import { useStore, setCompact } from '/static/js/store.js';
import { PipelineCard } from '/static/js/pipeline_card.js';

const pct = (v) => (v === null || v === undefined ? '–' : v.toFixed(1) + '%');

// ---------------------------------------------------------------------------------------------------------------- monitor risorse
function Metric({ label, icon, color, value, bar, testid }) {
  return html`<div class="metric" data-testid=${testid}>
    <div class="metric-head"><${Icon} name=${icon} size=${13} class=${'ico-' + color} /><span class="metric-name">${label}</span><span class="metric-value">${value}</span></div>
    <div class="metric-bar"><div class=${'metric-fill fill-' + color} style=${{ width: Math.max(0, Math.min(100, bar || 0)) + '%' }}></div></div>
  </div>`;
}
function Net({ label, icon, color, v, testid }) {
  return html`<div class="net" data-testid=${testid}><${Icon} name=${icon} size=${14} class=${'ico-' + color} /><span class="metric-name">${label}</span>
    <span class=${'net-value' + (v && v.active ? ' active-' + color : '')}>${v ? v.text : '0.0 KB/s'}</span></div>`;
}

function uptimeText(sec) {
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const p = (n) => String(n).padStart(2, '0');
  return `${t('web_uptime')}  ${p(h)}h ${p(m)}m ${p(s)}s`;
}

function ResourceMonitor() {
  const r = useStore((s) => s.resources);
  const [up, setUp] = useState(0);
  useEffect(() => { const id = setInterval(() => setUp((n) => n + 1), 1000); return () => clearInterval(id); }, []);
  return html`<div class="resource-monitor" data-testid="resources">
    <div class="rm-head"><span class="rm-title">${t('monitor_title')}</span><span class="rm-uptime" data-testid="uptime">${uptimeText(up)}</span></div>
    <div class="metric-grid">
      <${Metric} testid="m-cpu" label=${t('web_cpu')} icon="cpu" color="accent" value=${r ? pct(r.cpu) : '–'} bar=${r && r.cpu} />
      <${Metric} testid="m-ram" label=${t('web_ram')} icon="chip" color="success" value=${r ? pct(r.ram) : '–'} bar=${r && r.ram} />
      ${r && r.gpu_available ? html`<${Metric} testid="m-gpu" label=${t('web_gpu')} icon="gpu" color="purple" value=${r.gpu + '%'} bar=${r.gpu} />
        <${Metric} testid="m-vram" label=${t('web_vram')} icon="hardDrive" color="warn" value=${r.vram_used_gb === null ? '–' : r.vram_used_gb.toFixed(1) + 'GB'} bar=${r.vram_percent} />` : null}
      <${Net} testid="m-down" label=${t('web_download')} icon="arrowDown" color="accent" v=${r && r.down} />
      <${Net} testid="m-up" label=${t('web_upload')} icon="arrowUp" color="warn" v=${r && r.up} />
    </div>
  </div>`;
}

// ---------------------------------------------------------------------------------------------------------------- anteprima
const STATUS_KEY = { queued: 'mw_st_queued', processing: 'mw_st_processing', completed: 'mw_st_completed', failed: 'mw_st_failed' };

function Poster() {
  const pv = useStore((s) => s.preview);
  const current = useStore((s) => s.ui.current);
  const stable = pv.status === 'found' && pv.poster_id && current;
  return html`<div class="poster-area" data-testid="poster">
    ${stable ? html`<img class="poster-img" alt="" src=${'/api/poster/' + pv.poster_id} />`
      : html`<div class="poster-text" data-status=${pv.status}>
          ${pv.status === 'loading' ? '\n\n' + t('loading_preview') : (pv.status === 'failed' ? '❌\n\n' : '🎬\n\n') + t('no_preview')}</div>`}
  </div>`;
}

function InfoStrip() {
  const rows = useStore((s) => s.queue.rows);
  const current = useStore((s) => s.ui.current);
  const title = useStore((s) => s.title);
  const job = useStore((s) => s.job);
  const row = current ? rows.find((r) => r.path === current && r.status !== undefined) : null;
  const meta = row ? [row.size, row.progress > 0 ? row.progress + '%' : ''].filter(Boolean).join(' · ') : '';
  const lang = row ? ((row.ov_lang || job.target_language || '') + '').toUpperCase() : '';
  return html`<div class="info-strip" data-testid="info-strip">
    <div class="pills"><span class="pill pill-lang" style=${{ visibility: row ? 'visible' : 'hidden' }}>${'→ ' + lang}</span>
      <span class="pill pill-status" style=${{ visibility: row ? 'visible' : 'hidden' }}>${row ? t(STATUS_KEY[row.status] || row.status) : ''}</span></div>
    <div class="overlay-title" data-testid="overlay-title">${row ? title : ''}</div>
    <div class="overlay-meta" data-testid="overlay-meta">${meta}</div>
    <div class="overlay-progress"><div class="overlay-fill" style=${{ width: (row ? row.progress : 0) + '%' }}></div></div>
  </div>`;
}

export function CenterPanel() {
  const rows = useStore((s) => s.queue.rows);
  const current = useStore((s) => s.ui.current);
  const row = current ? rows.find((r) => r.path === current) : null;
  return html`<section class="panel center-panel" data-testid="center-panel">
    <div class="preview-header"><span class="panel-title">${t('web_preview_title')}</span>
      ${row ? html`<span class="filename-pill" data-testid="filename-pill">${row.filename}</span>` : null}</div>
    <div class="center-split">
      <div class="poster-stage"><${Poster} /><${InfoStrip} /></div>
      <${ResourceMonitor} />
    </div>
  </section>`;
}

// ---------------------------------------------------------------------------------------------------------------- pannello destro
function StatTile({ value, label, testid }) {
  return html`<div class="stat-tile" data-testid=${testid}><div class="stat-value">${value}</div><div class="stat-label">${label}</div></div>`;
}
function DiagTile({ value, label, icon, testid }) {
  return html`<div class="diag-tile" data-testid=${testid}><div class="diag-value" title=${value}>${value}</div>
    <div class="diag-label"><${Icon} name=${icon} size=${12} class="ico-dim" /><span>${label}</span></div></div>`;
}

function LogView() {
  const log = useStore((s) => s.log);
  const ref = useRef(null);
  useLayoutEffect(() => { const el = ref.current; if (el) el.scrollTop = el.scrollHeight; }, [log]);
  return html`<div class="log" data-testid="log" ref=${ref}>
    ${log.map((l) => html`<div class=${'log-line kind-' + l.kind} key=${l.id}>${l.text}</div>`)}</div>`;
}

export function RightPanel() {
  const st = useStore((s) => s.queue.stats);
  const opts = useStore((s) => s.logOptions);
  const d = useStore((s) => s.diag);
  return html`<section class="panel right-panel" data-testid="right-panel">
    <div class="panel-title-row"><span class="panel-title">${t('processing_log')}</span>
      <label class="check"><input type="checkbox" data-testid="compact" checked=${!!opts.compact}
        onChange=${(e) => setCompact(e.target.checked)} /><span class="box"></span><span>${t('compact_log')}</span></label></div>
    <div class="stat-row">
      <${StatTile} testid="stat-completed" value=${st ? st.completed : 0} label=${t('web_stat_completed')} />
      <${StatTile} testid="stat-progress" value=${st ? st.in_progress : 0} label=${t('web_stat_in_progress')} />
      <${StatTile} testid="stat-queued" value=${st ? st.queued : 0} label=${t('web_stat_queued')} />
      <${StatTile} testid="stat-eta" value=${st ? st.eta : '–'} label=${t('web_stat_eta')} />
    </div>
    <${PipelineCard} />
    <${LogView} />
    <div class="section-title">${t('mw_diagnostics')}</div>
    <div class="diag-row"><${DiagTile} testid="diag-elapsed" value=${d.elapsed} label=${t('web_diag_time')} icon="clock" />
      <${DiagTile} testid="diag-errors" value=${d.errors} label=${t('web_diag_errors')} icon="alert" /></div>
    <div class="diag-row"><${DiagTile} testid="diag-model" value=${d.model} label=${t('web_diag_model')} icon="mic" />
      <${DiagTile} testid="diag-translator" value=${d.translator} label=${t('web_diag_translator')} icon="globe" /></div>
    <div class="diag-row"><${DiagTile} testid="diag-engine" value=${d.engine} label=${t('web_diag_engine')} icon="chip" /></div>
  </section>`;
}
