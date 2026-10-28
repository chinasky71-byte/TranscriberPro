import { html, useState, useEffect, useLayoutEffect, useRef } from '/static/js/lib.js';
import { t } from '/static/js/i18n.js';
import { get, post } from '/static/js/api.js';
import { useStore, closeTool, getState } from '/static/js/store.js';
import { Checkbox } from '/static/js/form.js';
import { messageBox } from '/static/js/dialogs.js';
import { Confirm, FileBrowser } from '/static/js/modals.js';

const VIDEO_EXTS = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.m4v'];

/** Testo dello stato di una riga: quello del run in corso (pronta, in corso, %, ok, fallita, saltata) o quello del piano. */
function rowState(row, rt, running) {
  if (rt && (running || rt.kind)) {
    if (rt.kind === 'pct') return `${rt.pct}%`;
    if (rt.kind) return t('sync_batch_state_' + rt.kind);
    return '';
  }
  return t('sync_batch_state_' + row.state);
}

export function SyncDialog() {
  const sy = useStore((s) => s.tools.sync);
  const [video, setVideo] = useState('');
  const [srt, setSrt] = useState('');
  const [vdir, setVdir] = useState(sy.plan.dirs.video_dir);
  const [sdir, setSdir] = useState(sy.plan.dirs.srt_dir);
  const [recursive, setRecursive] = useState(!!sy.plan.dirs.recursive);
  const [tab, setTab] = useState(sy.mode === 'batch' ? 'batch' : 'single');
  const [browse, setBrowse] = useState(null);                 // {kind: 'video'|'srt'|'vdir'|'sdir'}
  const [ask, setAsk] = useState(null);                       // numero di coppie da confermare
  const [closing, setClosing] = useState(false);
  const running = sy.status === 'running';
  const seenRunning = useRef(running);
  const logRef = useRef(null);

  useEffect(() => {                                           // video predefinito: il file selezionato nella coda (come la GUI)
    const cur = getState().ui.current;
    if (cur && sy.status !== 'running') setVideo(cur);
  }, []);
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [sy.log]);
  useEffect(() => {                                           // esito del run visto in diretta: i messaggi della GUI (non si ripetono ricaricando)
    if (running) { seenRunning.current = true; return; }
    if (sy.status !== 'finished' || !seenRunning.current) return;
    seenRunning.current = false;
    const o = sy.outcome || {};
    if (o.kind === 'completed') {
      const output = sy.output_path || (o.video || '').replace(/\.[^.\\/]+$/, '') + '.synced.it.srt';
      messageBox('info', t('sync_done_title'), t('sync_done_msg', { output }));
    } else if (o.kind === 'error') sy.errors.forEach((e) => messageBox('error', t('error'), e));
    else if (o.kind === 'batch_done') messageBox('info', t('sync_done_title'), t('sync_batch_done', { ok: o.ok, fail: o.fail, skipped: o.skipped }));
  }, [sy.status]);
  useLayoutEffect(() => {
    const k = (e) => { if (e.key === 'Escape' && document.querySelectorAll('.modal-backdrop').length < 2) close(); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [running]);

  /** Chiudere il dialogo annulla e attende (fino a 35 s: un passo di Qwen puo' durare ~55 s), come la GUI; ricaricare non annulla. */
  async function close() {
    setClosing(true);
    if (running) await post('/api/tools/sync/cancel');
    for (let i = 0; i < 350; i++) { const r = await post('/api/tools/sync/reset'); if (r.ok) break; await new Promise((ok) => setTimeout(ok, 100)); }
    closeTool();
  }
  async function pair() {
    const r = await post('/api/tools/sync/scan', { video_dir: vdir, srt_dir: sdir, recursive });
    if (!r.ok) messageBox('warning', t('warning'), t('sync_batch_nothing'));
  }
  async function start(confirmed) {
    if (tab === 'batch') {
      const n = sy.plan.runnable;
      if (!n) { messageBox('warning', t('warning'), t('sync_batch_nothing')); return; }
      if (!confirmed) { setAsk(n); return; }
      const r = await post('/api/tools/sync/run', { mode: 'batch' });
      if (r.status === 409) messageBox('warning', t('sync_dialog_title'), t(r.data.blocked));
      return;
    }
    if (!video.trim()) { messageBox('warning', t('warning'), t('sync_missing_video')); return; }
    if (!srt.trim()) { messageBox('warning', t('warning'), t('sync_missing_srt')); return; }
    const r = await post('/api/tools/sync/run', { mode: 'single', video, srt });
    if (r.status === 409) messageBox('warning', t('sync_dialog_title'), t(r.data.blocked));
  }
  const pcts = sy.progress;
  const rows = sy.plan.rows, files = sy.plan.srt_files, sum = sy.plan.summary;
  const field = (testid, value, ph, kind) => html`<div class="inline-row"><input class="input" readonly data-testid=${testid} value=${value} placeholder=${ph} />
    <button class="btn btn-primary btn-fixed" data-testid=${testid + '-browse'} disabled=${running} onClick=${() => setBrowse({ kind })}>${t('browse')}</button></div>`;

  return html`<div class="modal-backdrop" onClick=${close}>
    <div class="tool-dialog sync-dialog" role="dialog" aria-modal="true" data-testid="sync-dialog" onClick=${(e) => e.stopPropagation()}>
      <div class="settings-header"><span class="settings-title">${t('sync_dialog_title')}</span>
        <button class="tool-btn" data-testid="sync-close" title=${t('web_close')} disabled=${closing} onClick=${close}>✕</button></div>
      <div class="tool-body">
        <div class="tabs-mini">
          <button class=${'tab-mini' + (tab === 'single' ? ' selected' : '')} data-tab="single" disabled=${running} onClick=${() => setTab('single')}>${t('sync_tab_single')}</button>
          <button class=${'tab-mini' + (tab === 'batch' ? ' selected' : '')} data-tab="batch" disabled=${running} onClick=${() => setTab('batch')}>${t('sync_tab_batch')}</button>
        </div>
        ${tab === 'single' ? html`<div class="page" data-testid="sync-single">
          <div class="inline-row"><span class="fixed-label">${t('sync_video_label')}</span>${field('sy-video', video, t('sync_video_ph'), 'video')}</div>
          <div class="inline-row"><span class="fixed-label">${t('sync_srt_label')}</span>${field('sy-srt', srt, t('sync_srt_ph'), 'srt')}</div>
        </div>` : html`<div class="page" data-testid="sync-batch">
          <div class="inline-row"><span class="fixed-label">${t('sync_batch_video_dir')}</span>${field('sy-vdir', vdir, '', 'vdir')}</div>
          <div class="inline-row"><span class="fixed-label">${t('sync_batch_srt_dir')}</span>${field('sy-sdir', sdir, '', 'sdir')}</div>
          <div class="inline-row spread"><${Checkbox} testid="sy-recursive" label=${t('sync_batch_subdirs')} checked=${recursive} disabled=${running} onChange=${setRecursive} />
            <button class="btn btn-primary" data-testid="sy-pair" disabled=${running} onClick=${pair}>${t('sync_batch_pair')}</button></div>
          <div class="sync-table-wrap"><table class="sync-table" data-testid="sy-table"><thead><tr><th></th><th>${t('sync_batch_col_video')}</th><th>${t('sync_batch_col_srt')}</th><th>${t('sync_batch_col_out')}</th><th>${t('sync_batch_col_state')}</th></tr></thead>
            <tbody>${rows.map((r) => html`<tr key=${r.idx} data-row=${r.idx}>
              <td><input type="checkbox" data-testid=${'sy-inc-' + r.idx} checked=${r.checked} disabled=${running}
                onChange=${(e) => post('/api/tools/sync/plan/include', { row: r.idx, include: e.target.checked })} /></td>
              <td title=${r.video}>${r.video_name}</td>
              <td><select class="select" data-testid=${'sy-srt-' + r.idx} disabled=${running} value=${r.srt || ''}
                onChange=${(e) => post('/api/tools/sync/plan/srt', { row: r.idx, value: e.target.value || null })}>
                <option value="">${t('sync_batch_none')}</option>${files.map((f) => html`<option value=${f.value} selected=${f.value === r.srt}>${f.label}</option>`)}</select></td>
              <td title=${r.output}>${r.output}</td>
              <td data-testid=${'sy-state-' + r.idx}>${rowState(r, sy.rows_rt[r.idx], running)}</td></tr>`)}</tbody></table></div>
          <div data-testid="sy-summary">${t('sync_batch_summary', { ready: sum.ready, check: sum.check, nosrt: sum.nosrt, left: sum.left })}</div>
        </div>`}
        <div class="tool-progress" data-testid="sy-progress"><div class="tool-progress-fill" style=${{ width: pcts + '%' }}></div><span class="progress-text">${pcts}%</span></div>
        <pre class="tool-log tall" ref=${logRef} data-testid="sy-log">${sy.log.join('\n')}</pre>
        <div class="btn-row end"><button class="btn btn-start" data-testid="sy-start" style=${{ flex: '0 0 200px' }} disabled=${running} onClick=${() => start(false)}>${t('sync_start')}</button>
          <button class="btn btn-primary" data-testid="sy-cancel" style=${{ flex: '0 0 120px' }} disabled=${!running} onClick=${() => post('/api/tools/sync/cancel')}>${t('cancel')}</button></div>
      </div>
      ${browse ? html`<${FileBrowser} mode=${browse.kind === 'vdir' || browse.kind === 'sdir' ? 'folder' : 'files'}
        title=${t({ video: 'sync_browse_video', srt: 'sync_browse_srt', vdir: 'sync_batch_browse_dir', sdir: 'sync_batch_browse_dir' }[browse.kind])}
        exts=${browse.kind === 'video' ? VIDEO_EXTS : browse.kind === 'srt' ? ['.srt'] : undefined} onCancel=${() => setBrowse(null)}
        onPick=${(p) => { const k = browse.kind; setBrowse(null); ({ video: setVideo, srt: setSrt, vdir: setVdir, sdir: setSdir })[k](p[0]); }} />` : null}
      ${ask ? html`<${Confirm} title=${t('sync_batch_start')} text=${t('sync_batch_confirm', { n: ask })} onNo=${() => setAsk(null)} onYes=${() => { setAsk(null); start(true); }} />` : null}
    </div></div>`;
}
