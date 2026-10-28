import { html, useState, useEffect, useCallback } from '/static/js/lib.js';
import { t } from '/static/js/i18n.js';
import { get, put, post } from '/static/js/api.js';
import { Group, Row, TextInput, TextArea, Checkbox, Radio, Select, Spin } from '/static/js/form.js';
import { messageBox } from '/static/js/dialogs.js';
import { Modal } from '/static/js/modals.js';

/** Legge /api/settings e lo tiene aggiornato: `reload` si richiama dopo ogni salvataggio. `active` rilegge quando la scheda torna visibile. */
function useSettings(active) {
  const [s, setS] = useState(null);
  const reload = useCallback(async () => { const r = await get('/api/settings'); if (r.ok) setS(r.data); return r.data; }, []);
  useEffect(() => { if (active) reload(); }, [active]);
  return [s, reload];
}

// ------------------------------------------------------------------------------------------------------------------- Generali
export function GeneralPage({ active }) {
  const [s, reload] = useSettings(active);
  const [shown, setShown] = useState(false);
  const [keyText, setKeyText] = useState(null);       // null = non toccata: la chiave resta quella salvata
  const [ping, setPing] = useState({ text: '', kind: '' });
  const [busy, setBusy] = useState(false);
  if (!s) return null;
  const g = s.general;
  const save = async (patch) => { await put('/api/settings/general', patch); reload(); };
  async function toggleShow() {
    const next = !shown;
    setShown(next);
    if (next && keyText === null) { const r = await post('/api/settings/reveal', { name: 'scanner_api_key' }); if (r.ok) setKeyText(r.data.value); }
  }
  async function test() {
    const url = (document.querySelector('[data-testid=gs-url]').value || '').trim();
    if (!url) { setPing({ text: t('gs_invalid_url'), kind: 'bad' }); return; }
    setBusy(true); setPing({ text: t('gs_testing'), kind: 'muted' });
    const r = await post('/api/settings/general/ping', { url, api_key: keyText === null ? undefined : keyText });
    setBusy(false);
    setPing(r.ok && r.data.ok ? { text: '✓ ' + r.data.message, kind: 'ok' } : { text: '✗ ' + (r.ok ? r.data.message : r.status), kind: 'bad' });
  }
  return html`<div class="page page-general">
    <${Group} title=${t('general_settings_lang_group')} testid="grp-lang">
      <${Row} label=${t('language_label')}>
        <${Select} testid="gs-lang" value=${g.language} onChange=${async (v) => { await save({ language: v }); messageBox('info', t('language_restart_title'), t('language_restart_msg')); }}
          options=${[{ value: 'auto', label: t('language_auto') }, { value: 'it', label: 'Italiano' }, { value: 'en', label: 'English' }]} /><//>
    <//>
    <div class="note">${t('language_restart_msg')}</div>
    <${Group} title="Library Scanner" testid="grp-scanner">
      <${Row} label=${t('web_gs_url')}><${TextInput} testid="gs-url" value=${g.scanner_url} placeholder="http://192.168.1.x:6680" onCommit=${(v) => save({ scanner_url: v })} /><//>
      <${Row} label=${t('web_gs_apikey')}>
        <div class="key-row"><${TextInput} testid="gs-key" placeholder=${g.scanner_api_key_set && keyText === null ? '••••••••••••' : 'API key'} revealed=${shown}
            value=${keyText === null ? '' : keyText} onCommit=${(v) => { setKeyText(v); save({ scanner_api_key: v }); }} />
          <button class="btn btn-primary btn-fixed" data-testid="gs-show" onClick=${toggleShow}>${shown ? t('gs_hide') : t('gs_show')}</button></div><//>
      <${Row} label=""><div class="ping-row"><button class="btn btn-primary" data-testid="gs-test" disabled=${busy} onClick=${test}>${t('gs_test_connection')}</button>
        <span class=${'ping-status ' + ping.kind} data-testid="gs-ping">${ping.text}</span></div><//>
      ${g.platform !== 'windows' ? html`<${Row} label=${t('web_gs_mounts')}><${TextArea} testid="gs-map" value=${g.scanner_path_map} tooltip=${t('gs_map_tip')}
        placeholder=${'\\\\192.168.1.12\\film=/mnt/film\nV:\\=/mnt/v'} onChange=${(v) => save({ scanner_path_map: v })} /><//>` : null}
    <//>
  </div>`;
}

// ---------------------------------------------------------------------------------------------------------------- Opzioni job
export function JobsPage({ active, go }) {
  const [s, reload] = useSettings(active);
  if (!s) return null;
  const j = s.job_options;
  const save = async (patch) => { await put('/api/settings/job_options', patch); reload(); };
  return html`<div class="page page-jobs">
    <div class="note muted-label">${t('job_defaults_intro')}</div>
    <div class="inline-row"><span>${t('srt_language_label')}</span>
      <${Select} testid="jo-lang" value=${j.target_language} onChange=${(v) => save({ target_language: v })}
        options=${j.languages.map((c) => ({ value: c, label: t('lang_name_' + c) }))} /></div>
    <${Checkbox} testid="jo-upload" label=${t('upload_opensubtitles')} checked=${j.opensubtitles_upload} onChange=${(v) => save({ opensubtitles_upload: v })} />
    <${Checkbox} testid="jo-mux" label=${t('mux_into_video_checkbox')} tooltip=${t('mux_into_video_tip')} checked=${j.mux_into_video} onChange=${(v) => save({ mux_into_video: v })} />
    <${Checkbox} testid="jo-gender" label=${t('gender_correction_checkbox')} tooltip=${t('gender_correction_tip')} checked=${j.gender_correction} onChange=${(v) => save({ gender_correction: v })} />
    <div class="inline-row spread"><span data-testid="jo-engine">${t('job_defaults_engine', { engine: j.engine_short })}</span>
      <button class="btn btn-primary" data-testid="jo-go-engine" onClick=${() => go('translation')}>${t('job_defaults_change_engine')}</button></div>
    <div class="inline-row spread"><span data-testid="jo-ocr">${t('job_defaults_ocr', { mode: t(j.ocr_mode_key) })}</span>
      <button class="btn btn-primary" data-testid="jo-go-ocr" onClick=${() => go('ocr')}>${t('job_defaults_change_ocr')}</button></div>
  </div>`;
}

// ------------------------------------------------------------------------------------------------------------------ Batch adattivo
export function BatchPage({ active }) {
  const [s, reload] = useSettings(active);
  const [form, setForm] = useState(null);
  const [status, setStatus] = useState(null);
  useEffect(() => { if (s) { const { status: st, ...vals } = s.adaptive_batch; setForm(vals); setStatus(st); } }, [s]);
  if (!form) return null;
  const set = (k, v) => setForm({ ...form, [k]: v });
  async function toggle(on) {
    set('enabled', on);
    const r = await get('/api/settings/adaptive_batch/status?enabled=' + on);
    if (r.ok) setStatus(r.data);
  }
  async function save() {
    const { enabled, initial_size, min_size, max_size, warmup_batches, high_threshold, low_threshold } = form;
    const r = await put('/api/settings/adaptive_batch', { enabled, initial_size, min_size, max_size, warmup_batches, high_threshold, low_threshold });
    if (r.ok) { setStatus(r.data.status); reload(); }
  }
  async function defaults() { const r = await get('/api/settings/adaptive_batch/defaults'); if (r.ok) setForm(r.data); }
  const statusText = status ? (status.key === 'abs_active_status'
    ? t('abs_active_status', { initial: status.initial ? status.initial : t('abs_autodetect'), min: status.min, max: status.max, warmup: status.warmup })
    : t(status.key)) : '';
  const off = !form.enabled;
  return html`<div class="page page-batch">
    <${Group} title=${t('abs_status_group')}><${Checkbox} testid="ab-enable" label=${t('abs_enable')} tooltip=${t('abs_enable_tip')} checked=${form.enabled} onChange=${toggle} />
      <div class="muted-small" data-testid="ab-status">${statusText}</div><//>
    <${Group} title=${t('abs_batch_group')}>
      <${Row} label=${t('abs_initial_label')} tooltip=${t('abs_initial_tip')}><${Spin} testid="ab-initial" value=${form.initial_size} min=${0} max=${64} special=${t('abs_autodetect')} disabled=${off} onChange=${(v) => set('initial_size', v)} /><//>
      <${Row} label=${t('abs_min_label')} tooltip=${t('abs_min_tip')}><${Spin} testid="ab-min" value=${form.min_size} min=${1} max=${16} disabled=${off} onChange=${(v) => set('min_size', v)} /><//>
      <${Row} label=${t('abs_max_label')} tooltip=${t('abs_max_tip')}><${Spin} testid="ab-max" value=${form.max_size} min=${1} max=${64} disabled=${off} onChange=${(v) => set('max_size', v)} /><//>
    <//>
    <${Group} title=${t('abs_warmup_group')}>
      <${Row} label=${t('abs_warmup_label')} tooltip=${t('abs_warmup_tip')}><${Spin} testid="ab-warmup" value=${form.warmup_batches} min=${0} max=${20} disabled=${off} onChange=${(v) => set('warmup_batches', v)} /><//>
      <${Row} label=${t('abs_high_thresh')} tooltip=${t('abs_high_tip')}><${Spin} testid="ab-high" value=${form.high_threshold} min=${0.5} max=${1} step=${0.05} decimals=${2} disabled=${off} onChange=${(v) => set('high_threshold', v)} /><//>
      <${Row} label=${t('abs_low_thresh')} tooltip=${t('abs_low_tip')}><${Spin} testid="ab-low" value=${form.low_threshold} min=${0.1} max=${0.9} step=${0.05} decimals=${2} disabled=${off} onChange=${(v) => set('low_threshold', v)} /><//>
    <//>
    <div class="note small">${t('abs_note')}</div>
    <div class="btn-row spread"><button class="btn btn-primary" data-testid="ab-reset" onClick=${defaults}>${t('abs_restore_defaults')}</button>
      <button class="btn btn-primary" data-testid="ab-save" onClick=${save}>${t('abs_save')}</button></div>
  </div>`;
}

// ------------------------------------------------------------------------------------------------------------------------- OCR
export function OcrPage({ active }) {
  const [s, reload] = useSettings(active);
  if (!s) return null;
  const o = s.ocr;
  const save = async (patch) => { await put('/api/settings/ocr', patch); reload(); };
  return html`<div class="page page-ocr">
    <${Group} title=${t('ocr_strategy_group')}>
      <${Radio} name="ocr-strategy" testid="oc-review" checked=${o.strategy === 'review'} onChange=${() => save({ strategy: 'review' })}>${t('ocr_strategy_review')}<//>
      <div class="comment">${t('ocr_strategy_review_comment')}</div>
      <${Radio} name="ocr-strategy" testid="oc-auto" checked=${o.strategy === 'auto'} onChange=${() => save({ strategy: 'auto' })}>${t('ocr_strategy_auto')}<//>
      <div class="comment">${t('ocr_strategy_auto_comment')}</div>
    <//>
    <${Group} title=${t('ocr_engine_group')}>
      <${Row} label=${t('ocr_language_label')} tooltip=${t('ocr_language_tip')}><${TextInput} testid="oc-lang" value=${o.language} placeholder=${t('ocr_language_ph')} onCommit=${(v) => save({ language: v })} /><//>
      <${Row} label=${t('ocr_conf_threshold_label')} tooltip=${t('ocr_conf_threshold_tip')}><${Spin} testid="oc-conf" value=${o.conf_threshold} min=${0} max=${100} suffix=" %" onChange=${(v) => save({ conf_threshold: v })} /><//>
      <${Row} label=${t('ocr_workers_label')} tooltip=${t('ocr_workers_tip')}><${Spin} testid="oc-workers" value=${o.workers} min=${0} max=${32} special=${t('ocr_workers_auto')} onChange=${(v) => save({ workers: v })} /><//>
      <${Row} label=${t('ocr_tesseract_path_label')} tooltip=${t('ocr_tesseract_path_tip')}><${TextInput} testid="oc-tess" value=${o.tesseract_path} placeholder=${t('ocr_tesseract_path_ph')} onCommit=${(v) => save({ tesseract_path: v })} /><//>
    <//>
    <${Group} title=${t('ocr_writeback_group')}>
      <div class="inline-row"><span>${t('ocr_writeback_label')}</span>
        <${Select} testid="oc-writeback" value=${o.writeback} tooltip=${t('ocr_writeback_tip')} onChange=${(v) => save({ writeback: v })}
          options=${[{ value: 'mux', label: t('ocr_writeback_mux') }, { value: 'sidecar', label: t('ocr_writeback_sidecar') }]} /></div>
    <//>
  </div>`;
}

// ------------------------------------------------------------------------------------------------------------------ OpenSubtitles
export function OpenSubtitlesPage({ active }) {
  const [s, reload] = useSettings(active);
  const [com, setCom] = useState({ username: '', password: null, api_key: null });
  const [org, setOrg] = useState({ username: '', password: null });
  const [rev, setRev] = useState({});
  const [testing, setTesting] = useState(false);
  const [help, setHelp] = useState(false);
  const os = s && s.opensubtitles;
  useEffect(() => { if (os) { setCom((c) => ({ ...c, username: os.com_username })); setOrg((c) => ({ ...c, username: os.org_username })); } }, [os && os.com_username, os && os.org_username]);
  if (!os) return null;
  const configured = os.configured;
  const upd = async (patch) => { await put('/api/settings/opensubtitles', patch); reload(); };
  const saved = () => messageBox('info', t('os_creds_saved_title'), t('os_creds_saved_msg'));
  const missing = () => messageBox('warning', t('os_missing_fields_title'), t('os_missing_fields_msg'));
  async function saveCom() {
    const body = { username: com.username, ...(com.password !== null ? { password: com.password } : {}), ...(com.api_key !== null ? { api_key: com.api_key } : {}) };
    const r = await put('/api/settings/opensubtitles/com', body);
    if (!r.ok) return missing();
    setCom({ username: r.data.com_username, password: null, api_key: null }); setRev({}); reload(); saved();
  }
  async function saveOrg() {
    const body = { username: org.username, ...(org.password !== null ? { password: org.password } : {}) };
    const r = await put('/api/settings/opensubtitles/org', body);
    if (!r.ok) return missing();
    setOrg({ username: r.data.org_username, password: null }); setRev({}); reload(); saved();
  }
  async function test() {
    setTesting(true);
    const r = await post('/api/settings/opensubtitles/test');
    setTesting(false);
    if (!r.ok) return messageBox('error', t('os_error_title'), t('os_error_msg', { error: r.status }));
    const k = r.data;
    if (k.kind === 'missing_creds') messageBox('warning', t('os_missing_creds_title'), t('os_missing_creds_msg'));
    else if (k.kind === 'ok') messageBox('info', t('os_test_ok_title'), t('os_test_ok_msg'));
    else if (k.kind === 'fail') messageBox('error', t('os_test_fail_title'), t('os_test_fail_msg') + (k.implementation === 'xmlrpc' ? '\n\n' + t('os_xmlrpc_org_com_hint') : ''));
    else messageBox('error', t('os_error_title'), t('os_error_msg', { error: k.error }));
  }
  async function reveal(name, key, setter) {
    if (rev[name]) { setRev({ ...rev, [name]: false }); return; }
    const r = await post('/api/settings/reveal', { name });
    if (r.ok) { setter((v) => (v[key] === null ? { ...v, [key]: r.data.value } : v)); setRev({ ...rev, [name]: true }); }
  }
  const pw = (isSet, val, ph) => (val === null ? { placeholder: isSet ? '••••••••' : ph, value: '' } : { placeholder: ph, value: val });
  return html`<div class="page page-os">
    <${Group} title=${t('os_upload_group')}>
      <div class="status-label" data-testid="os-status">${configured ? t('os_configured') : t('os_not_configured') + '\n' + t('os_not_available')}</div>
      <div class=${'credentials-label' + (configured ? '' : ' hint')} data-testid="os-account">${configured ? t('os_account', { username: os.username }) : t('os_configure_hint')}</div>
    <//>
    <${Group} title=${t('os_credentials_group_org')}>
      <${Row} label="Username:"><${TextInput} testid="os-org-user" value=${org.username} placeholder=${t('os_username_ph')} onCommit=${(v) => setOrg({ ...org, username: v })} /><//>
      <${Row} label="Password:"><div class="key-row"><${TextInput} testid="os-org-pass" revealed=${!!rev.os_org_password} onCommit=${(v) => setOrg({ ...org, password: v })} ...${pw(os.org_password_set, org.password, t('os_password_ph'))} />
        <button class="btn btn-primary btn-fixed" data-testid="os-org-show" onClick=${() => reveal('os_org_password', 'password', setOrg)}>${rev.os_org_password ? t('gs_hide') : t('gs_show')}</button></div><//>
      <${Row} label=""><button class="btn btn-primary wide" data-testid="os-org-save" onClick=${saveOrg}>${t('os_save_creds')}</button><//>
    <//>
    <${Group} title=${t('os_credentials_group_com')}>
      <${Row} label="Username:"><${TextInput} testid="os-com-user" value=${com.username} placeholder=${t('os_username_ph')} onCommit=${(v) => setCom({ ...com, username: v })} /><//>
      <${Row} label="Password:"><div class="key-row"><${TextInput} testid="os-com-pass" revealed=${!!rev.os_com_password} onCommit=${(v) => setCom({ ...com, password: v })} ...${pw(os.com_password_set, com.password, t('os_password_ph'))} />
        <button class="btn btn-primary btn-fixed" data-testid="os-com-show" onClick=${() => reveal('os_com_password', 'password', setCom)}>${rev.os_com_password ? t('gs_hide') : t('gs_show')}</button></div><//>
      <${Row} label="API Key:"><div class="key-row"><${TextInput} testid="os-com-key" revealed=${!!rev.os_com_api_key} onCommit=${(v) => setCom({ ...com, api_key: v })} ...${pw(os.com_api_key_set, com.api_key, t('os_apikey_ph'))} />
        <button class="btn btn-primary btn-fixed" data-testid="os-com-keyshow" onClick=${() => reveal('os_com_api_key', 'api_key', setCom)}>${rev.os_com_api_key ? t('gs_hide') : t('gs_show')}</button></div><//>
      <${Row} label=""><button class="btn btn-primary wide" data-testid="os-com-save" onClick=${saveCom}>${t('os_save_creds')}</button><//>
    <//>
    <${Group} title=${t('os_settings_group')}>
      <${Checkbox} testid="os-upload" label=${t('upload_opensubtitles')} checked=${configured && os.upload_enabled} disabled=${!configured} onChange=${(v) => upd({ upload_enabled: v })} />
      <div class="inline-row"><span title=${t('os_api_method_tip')}>${t('os_api_method')}</span>
        <${Select} testid="os-impl" value=${os.implementation} tooltip=${t('os_api_method_tip')} onChange=${(v) => upd({ implementation: v })}
          options=${[{ value: 'xmlrpc', label: 'XML-RPC (opensubtitles.org)', tooltip: t('os_xmlrpc_tooltip') }, { value: 'rest', label: 'REST (opensubtitles.com)', tooltip: t('os_rest_tooltip') }]} /></div>
    <//>
    <div class="btn-row"><button class="btn btn-primary" data-testid="os-test" title=${t('os_test_conn_tip')} disabled=${!configured || testing} onClick=${test}>${testing ? t('os_testing') : t('os_test_conn')}</button>
      <button class="btn btn-primary" data-testid="os-help" title=${t('os_configure_tip')} onClick=${() => setHelp(true)}>${t('os_configure')}</button></div>
    ${help ? html`<${Modal} title=${t('os_guide_title')} onClose=${() => setHelp(false)} testid="os-guide"><div class="guide">${t('web_os_guide_text')}</div><//>` : null}
  </div>`;
}
