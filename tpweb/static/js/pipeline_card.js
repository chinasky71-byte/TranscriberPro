import { html, useEffect, useState } from '/static/js/lib.js';
import { t } from '/static/js/i18n.js';
import { useStore, setPipelineOpen, getState } from '/static/js/store.js';

const STATE_TEXT = { done: 'step_state_done', disabled: 'step_state_disabled', not_needed: 'step_state_not_needed', failed: 'step_state_failed',
  stopped: 'step_state_stopped' };
const ROW_H = 30, ACTIVE_ROW_H = 44, HEADER_H = 32, BOTTOM_PAD = 8;

/** Percentuale STIMATA di un passo breve senza misura reale (min 95): 95 * (1 - e^(-t/tau)); stessa formula di core/jobs/step_plan.est_pct. */
export function estPct(step, nowSec) {
  if (!step.est_tau || !step.started_at) return 0;
  const dt = Math.max(0, nowSec - step.started_at);
  return Math.min(95, Math.floor(95 * (1 - Math.exp(-dt / step.est_tau))));
}

function Circle({ step }) {
  const s = step.status;
  if (s === 'done') return html`<span class="pc pc-done"><svg width="22" height="22" viewBox="0 0 22 22"><path d="M7 11.5l3 3L15.5 8" fill="none" stroke="var(--on-accent)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></span>`;
  if (s === 'active') return html`<span class="pc pc-active"><span class="pc-dot"></span></span>`;
  if (s === 'disabled' || s === 'not_needed') return html`<span class="pc pc-off"><svg width="22" height="22" viewBox="0 0 22 22"><path d="M8 8l6 6M8 14l6-6" stroke="var(--fg-disabled)" stroke-width="1.3" fill="none"/></svg></span>`;
  if (s === 'failed') return html`<span class="pc pc-failed"><svg width="22" height="22" viewBox="0 0 22 22"><path d="M11 6v6" stroke="var(--on-accent)" stroke-width="2" stroke-linecap="round"/><circle cx="11" cy="16" r="1" fill="var(--on-accent)"/></svg></span>`;
  if (s === 'stopped') return html`<span class="pc pc-stopped"><svg width="22" height="22" viewBox="0 0 22 22"><rect x="8" y="8" width="6" height="6" fill="none" stroke="var(--on-accent)" stroke-width="2"/></svg></span>`;
  return html`<span class="pc pc-pending">${step.order === null || step.order === undefined ? '' : step.order}</span>`;
}

function Row({ step, now }) {
  const s = step.status;
  const active = s === 'active';
  const pct = active ? (step.pct !== null && step.pct !== undefined ? step.pct : (step.est_tau ? estPct(step, now) : null)) : null;
  let right = '';
  if (STATE_TEXT[s]) right = t(STATE_TEXT[s]);
  return html`<div class=${'prow prow-' + s} data-step=${step.key} data-status=${s} style=${{ height: (active ? ACTIVE_ROW_H : ROW_H) + 'px', '--h': (active ? ACTIVE_ROW_H : ROW_H) + 'px' }}>
    <${Circle} step=${step} />
    <span class="prow-label">${t(step.label_key)}</span>
    ${active && step.eta ? html`<span class="prow-eta">${step.eta}</span>` : null}
    ${active && pct !== null ? html`<span class="prow-pct">${pct}%</span>` : html`<span class=${'prow-right right-' + s}>${right}</span>`}
    ${active ? html`<div class="prow-bar"><div class=${'prow-fill' + (pct === null ? ' indeterminate' : '')} style=${pct === null ? {} : { width: Math.max(0, Math.min(100, pct)) + '%' }}></div></div>` : null}
  </div>`;
}

/** «Pipeline in corso»: elenco dei passi del file in lavorazione (solo con Log Sintetico). Dati e piano arrivano dal server. */
export function PipelineCard() {
  const steps = useStore((s) => s.queue.steps);
  const opts = useStore((s) => s.logOptions);
  const offset = useStore((s) => s.clockOffset);
  const [tick, setTick] = useState(0);
  const animated = !!(steps && opts.pipeline_open && steps.steps.some((x) => x.status === 'active' && x.est_tau));
  useEffect(() => {
    if (!animated) return undefined;
    const id = setInterval(() => setTick((n) => n + 1), 100);          // la barra stimata si ridisegna da sola (80 ms in Qt)
    return () => clearInterval(id);
  }, [animated]);
  if (!steps || !opts.compact) return null;
  const now = Date.now() / 1000 + offset;
  return html`<div class="pipeline-card" data-testid="pipeline-card" data-open=${String(opts.pipeline_open)}>
    <div class="pipeline-head" data-testid="pipeline-head" onClick=${() => setPipelineOpen(!opts.pipeline_open)}>
      <span class="pipeline-title">${t('pipeline_in_progress')}</span><span class="pipeline-pill">${steps.done}/${steps.total}</span>
      <span class="pipeline-file">${steps.file_name}</span>
      <svg class="pipeline-chev" width="14" height="14" viewBox="0 0 14 14"><path d=${opts.pipeline_open ? 'M3 5l4 4 4-4' : 'M5 3l4 4-4 4'} fill="none" stroke="var(--fg-3)" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </div>
    ${opts.pipeline_open ? html`<div class="pipeline-rows">${steps.steps.map((st) => html`<${Row} key=${st.key} step=${st} now=${now} />`)}</div>` : null}
  </div>`;
}
