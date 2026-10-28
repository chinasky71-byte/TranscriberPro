import { html } from '/static/js/lib.js';
import { t } from '/static/js/i18n.js';
import { Icon } from '/static/js/icon.js';
import { useStore } from '/static/js/store.js';

const pct = (v) => (v === null || v === undefined ? '–' : v.toFixed(1) + '%');

function Metric({ label, icon, color, value, bar, testid }) {
  return html`<div class="metric" data-testid=${testid}>
    <div class="metric-head"><${Icon} name=${icon} size=${13} class=${'ico-' + color} /><span class="metric-name">${label}</span><span class="metric-value">${value}</span></div>
    <div class="metric-bar"><div class=${'metric-fill fill-' + color} style=${{ width: Math.max(0, Math.min(100, bar || 0)) + '%' }}></div></div>
  </div>`;
}
function Net({ label, icon, color, v, testid }) {
  return html`<div class="net" data-testid=${testid}><${Icon} name=${icon} size=${13} class=${'ico-' + color} /><span class="metric-name">${label}</span>
    <span class=${'net-value' + (v && v.active ? ' active-' + color : '')}>${v ? v.text : '0.0 KB/s'}</span></div>`;
}

function ResourceMonitor() {
  const r = useStore((s) => s.resources);
  return html`<div class="resource-monitor" data-testid="resources">
    <div class="rm-head"><span class="rm-title">${t('monitor_title')}</span><span class="rm-uptime">${t('web_uptime')}  00h 00m 00s</span></div>
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

export function CenterPanel() {
  return html`<section class="panel center-panel" data-testid="center-panel">
    <div class="panel-title">${t('web_preview_title')}</div>
    <div class="poster"><span class="poster-icon">🎬</span><span class="poster-text">${t('no_preview')}</span></div>
    <${ResourceMonitor} />
  </section>`;
}

function StatTile({ value, label, testid }) {
  return html`<div class="stat-tile" data-testid=${testid}><div class="stat-value">${value}</div><div class="stat-label">${label}</div></div>`;
}

export function RightPanel() {
  const st = useStore((s) => s.queue.stats);
  const log = useStore((s) => s.log);
  return html`<section class="panel right-panel" data-testid="right-panel">
    <div class="panel-title-row"><span class="panel-title">${t('processing_log')}</span></div>
    <div class="stat-row">
      <${StatTile} testid="stat-completed" value=${st ? st.completed : 0} label=${t('web_stat_completed')} />
      <${StatTile} testid="stat-progress" value=${st ? st.in_progress : 0} label=${t('web_stat_in_progress')} />
      <${StatTile} testid="stat-queued" value=${st ? st.queued : 0} label=${t('web_stat_queued')} />
      <${StatTile} testid="stat-eta" value=${st ? st.eta : '–'} label=${t('web_stat_eta')} />
    </div>
    <div class="log" data-testid="log">${log.slice(-200).map((l) => html`<div class="log-line">${l}</div>`)}</div>
  </section>`;
}
