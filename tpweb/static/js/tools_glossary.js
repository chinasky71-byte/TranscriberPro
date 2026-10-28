import { html, useState, useEffect, useLayoutEffect } from '/static/js/lib.js';
import { t } from '/static/js/i18n.js';
import { get, post } from '/static/js/api.js';
import { useStore, closeTool } from '/static/js/store.js';
import { Group, Checkbox, TextInput } from '/static/js/form.js';
import { messageBox } from '/static/js/dialogs.js';
import { Confirm, FileBrowser } from '/static/js/modals.js';

/** Una card per candidato: approvazione + resa + cluster ed esempi (CollapsibleCard della GUI). */
function TermCard({ rec, value, onChange }) {
  const [open, setOpen] = useState(rec.status !== 'auto');
  const icon = { auto: '✓', review: '?', reject: '✕' }[rec.status || 'review'] || '?';
  const info = `${t('glossary_occurrences')}: ${rec.occurrences || 0} · ${t('glossary_align_channel')}: ${rec.align_verdict || 'n/a'} (${t('glossary_extracted', { n: rec.align_extracted || 0 })}) · `
    + `${t('glossary_qwen_channel')}: ${rec.qwen_verdict || 'n/a'} (${t('glossary_extracted_cov', { n: rec.qwen_extracted || 0, cov: rec.qwen_coverage_text })}) · ${rec.reason || ''}`;
  return html`<div class=${'term-card' + (open ? ' open' : '')} data-term=${rec.term}>
    <button class="term-head" onClick=${() => setOpen(!open)}><span class="term-title">${rec.term}  →  ${rec.dominant || '?'}</span><span class="term-sum">${icon} ${rec.status || 'review'}</span></button>
    ${open ? html`<div class="term-body">
      <div class="term-approve"><${Checkbox} testid=${'gl-ok-' + rec.term} label=${t('glossary_approve_term')} checked=${value.approved} onChange=${(v) => onChange({ ...value, approved: v })} />
        <span>${t('glossary_rendering_label')}</span>
        <input class="input" data-testid=${'gl-rend-' + rec.term} value=${value.rendering} onInput=${(e) => onChange({ ...value, rendering: e.target.value })} /></div>
      <div class="caption" data-testid=${'gl-info-' + rec.term}>${info}</div>
      ${(rec.clusters || []).slice(0, 6).map((c) => html`<div><div class="cluster">「${c.text}」 × ${c.n}</div>
        ${(c.examples || []).slice(0, 2).map((ex) => html`<div class="example">   EN: ${(ex.en || '').slice(0, 70)}\n   IT: ${(ex.it || '').slice(0, 70)}</div>`)}</div>`)}
    </div>` : null}</div>`;
}

export function GlossaryDialog() {
  const g = useStore((s) => s.tools.glossary);
  const [folder, setFolder] = useState(g.run_info ? g.run_info.show_dir : '');
  const [name, setName] = useState(g.run_info ? g.run_info.name : '');
  const [names, setNames] = useState([]);
  const [tmdb, setTmdb] = useState({ id: g.run_info ? g.run_info.tmdb_id : null, label: null });
  const [browse, setBrowse] = useState(false);
  const [askNoTmdb, setAskNoTmdb] = useState(false);
  const [vals, setVals] = useState({});                     // termine -> {approved, rendering}
  const running = g.status === 'running';

  useEffect(() => {                                         // valori iniziali delle card quando arriva (o si ritrova) il report
    if (g.report && g.report.candidates) {
      const v = {};
      g.report.candidates.forEach((c) => { v[c.term] = { approved: c.status === 'auto', rendering: c.dominant || '' }; });
      setVals(v);
    }
  }, [g.report]);
  useLayoutEffect(() => {
    const k = (e) => { if (e.key === 'Escape' && document.querySelectorAll('.modal-backdrop').length < 2) close(); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [running]);

  /** Chiudere il dialogo annulla un run in corso (e azzera l'esito), come la GUI; ricaricare la pagina NON lo fa. */
  async function close() {
    if (running) {
      await post('/api/tools/glossary/cancel');
      for (let i = 0; i < 60; i++) { const r = await post('/api/tools/glossary/reset'); if (r.ok) break; await new Promise((ok) => setTimeout(ok, 100)); }
    } else await post('/api/tools/glossary/reset');
    closeTool();
  }
  async function picked(path) {
    setBrowse(false);
    setFolder(path);
    const r = await get('/api/tools/glossary/names?folder=' + encodeURIComponent(path));
    if (!r.ok) return;
    setNames(r.data.names);
    if (!name.trim() && r.data.names.length) setName(r.data.names[0]);
    setTmdb({ id: null, label: r.data.is_season ? `${t('glossary_tmdb_not_resolved')} (${r.data.parent_name} → ${r.data.folder_name})` : null });
  }
  async function resolve() {
    const typed = name.trim();
    const ordered = (typed ? [typed] : []).concat(names.filter((c) => c.toLowerCase() !== typed.toLowerCase()));
    if (!ordered.length) return;
    setTmdb({ id: null, label: t('glossary_tmdb_resolving') });
    const r = await post('/api/tools/glossary/resolve', { names: ordered });
    if (!r.ok || !r.data.found) { setTmdb({ id: null, label: t('glossary_tmdb_not_found') }); return; }
    if (r.data.title && r.data.title.trim().toLowerCase() !== name.trim().toLowerCase()) setName(r.data.title);
    setTmdb({ id: r.data.tmdb_id, label: `TMDB #${r.data.tmdb_id} — ${r.data.title}` });
  }
  async function start(confirmed) {
    if (!folder.trim()) { messageBox('warning', t('glossary_dialog_title'), t('glossary_error_no_folder')); return; }
    if (tmdb.id === null && !confirmed) { setAskNoTmdb(true); return; }
    const r = await post('/api/tools/glossary/run', { show_dir: folder, name, tmdb_id: tmdb.id, names });
    if (r.status === 422) messageBox('warning', t('glossary_dialog_title'), t('glossary_error_no_folder'));
    else if (r.status === 409 && r.data.blocked && r.data.blocked !== 'running') messageBox('warning', t('tools_glossary'), t(r.data.blocked));
  }
  async function save() {
    const rows = (g.report.candidates || []).map((c) => ({ term: c.term, approved: !!(vals[c.term] || {}).approved, rendering: (vals[c.term] || {}).rendering || '' }));
    const r = await post('/api/tools/glossary/save', { rows, tmdb_id: tmdb.id });
    const title = t('glossary_dialog_title');
    if (r.ok && r.data.ok) messageBox('info', title, t('glossary_save_success', { n: r.data.saved, path: r.data.path }));
    else if (r.data && r.data.reason === 'no_terms') messageBox('info', title, t('glossary_no_terms_approved'));
    else if (r.data && r.data.reason === 'no_tmdb') messageBox('warning', title, t('glossary_error_no_tmdb_save'));
    else messageBox('error', title, t('glossary_save_error', { error: (r.data && r.data.error) || r.status }));
  }

  const gateBad = g.gate && g.gate.ok === false;
  const cands = (g.report && g.report.candidates) || [];
  let status = '';
  if (gateBad) status = t('glossary_gate_insufficient', { blocks: g.gate.blocks || 0, need: g.gate.need_blocks || 0 });
  else if (g.status === 'failed') status = t('glossary_status_failed', { msg: g.error && g.error.key ? t(g.error.key, { error: g.error.msg }) : (g.error ? g.error.msg : '') });
  else if (g.status === 'done') status = t('glossary_status_done', { n: cands.length });
  else if (running) status = (g.phase || g.done || g.total) ? (g.total ? `[${g.phase}] ${g.msg} (${g.done}/${g.total})` : g.phase) : t('glossary_status_running');
  const qwenErr = g.report && g.report.qwen_channel_error;
  const logLines = qwenErr ? [...g.log, t('glossary_qwen_channel_failed', { msg: qwenErr })] : g.log;

  return html`<div class="modal-backdrop" onClick=${close}>
    <div class="tool-dialog glossary-dialog" role="dialog" aria-modal="true" data-testid="glossary-dialog" onClick=${(e) => e.stopPropagation()}>
      <div class="settings-header"><span class="settings-title">${t('glossary_dialog_title')}</span>
        <button class="tool-btn" data-testid="glossary-close" title=${t('web_close')} onClick=${close}>✕</button></div>
      <div class="tool-body">
        ${!g.venv_available ? html`<div class="warn-box" data-testid="gl-venv">${t('glossary_venv_missing')}</div>` : null}
        <div class="inline-row"><span class="fixed-label">${t('glossary_show_folder')}</span>
          <input class="input" data-testid="gl-folder" value=${folder} disabled=${running} onInput=${(e) => setFolder(e.target.value)} />
          <button class="btn btn-primary" data-testid="gl-browse" disabled=${running} onClick=${() => setBrowse(true)}>${t('glossary_browse')}</button></div>
        <div class="inline-row"><span class="fixed-label">${t('glossary_show_name')}</span>
          <input class="input" data-testid="gl-name" value=${name} disabled=${running} onInput=${(e) => { setName(e.target.value); setTmdb({ id: null, label: null }); }} />
          <button class="btn btn-primary" data-testid="gl-resolve" disabled=${running} onClick=${resolve}>${t('glossary_resolve_tmdb')}</button></div>
        <div class="caption" data-testid="gl-tmdb">${tmdb.label || t('glossary_tmdb_not_resolved')}</div>
        <div class="btn-row"><button class="btn btn-primary" data-testid="gl-run" disabled=${running} onClick=${() => start(false)}>${t('glossary_run')}</button>
          <button class="btn btn-primary" data-testid="gl-cancel" disabled=${!running} onClick=${() => post('/api/tools/glossary/cancel')}>${t('glossary_cancel')}</button></div>
        <div class=${'tool-progress' + (running && !g.total ? ' indeterminate' : '')} data-testid="gl-progress"><div class="tool-progress-fill" style=${{ width: (g.total ? Math.round(100 * g.done / g.total) : (g.status === 'done' ? 100 : 0)) + '%' }}></div></div>
        <div data-testid="gl-status">${status}</div>
        <pre class="tool-log" data-testid="gl-log">${logLines.join('\n')}</pre>
        <div class="warn-box">${t('glossary_retroactive_warning')}</div>
        <div class="cards" data-testid="gl-cards">${cands.map((c) => html`<${TermCard} key=${c.term} rec=${c} value=${vals[c.term] || { approved: false, rendering: '' }}
          onChange=${(v) => setVals({ ...vals, [c.term]: v })} />`)}</div>
        <div class="btn-row end"><button class="btn btn-primary" data-testid="gl-save" disabled=${!cands.length} onClick=${save}>${t('glossary_save')}</button></div>
      </div>
      ${browse ? html`<${FileBrowser} mode="folder" title=${t('glossary_show_folder')} onCancel=${() => setBrowse(false)} onPick=${(p) => picked(p[0])} />` : null}
      ${askNoTmdb ? html`<${Confirm} title=${t('glossary_dialog_title')} text=${t('glossary_confirm_no_tmdb')} onNo=${() => setAskNoTmdb(false)} onYes=${() => { setAskNoTmdb(false); start(true); }} />` : null}
    </div></div>`;
}
