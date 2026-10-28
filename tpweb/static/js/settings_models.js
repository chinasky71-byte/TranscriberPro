import { html, useState, useEffect, useCallback } from '/static/js/lib.js';
import { t } from '/static/js/i18n.js';
import { get, put, post } from '/static/js/api.js';
import { useStore, getState, setState } from '/static/js/store.js';
import { Group, Row, TextInput, Checkbox, Radio, Select, Spin } from '/static/js/form.js';
import { messageBox } from '/static/js/dialogs.js';
import { Confirm, FileBrowser } from '/static/js/modals.js';

// ---------------------------------------------------------------------------------------------------------------- Trascrizione
export function TranscriptionPage({ active }) {
  const [s, setS] = useState(null);
  const load = useCallback(async () => { const r = await get('/api/settings/transcription'); if (r.ok) setS(r.data); }, []);
  useEffect(() => { if (active) load(); }, [active]);
  if (!s) return null;
  const save = async (patch) => { const r = await put('/api/settings/transcription', patch); if (r.ok) setS(r.data); };
  return html`<div class="page page-transcription">
    <div class="note">${t('profiles_desc')}</div>
    <${Group} title=${t('engine_group')}>
      <div class="inline-row"><span>${t('engine_label')}</span>
        <${Select} testid="tr-engine" value=${s.engine_mode} tooltip=${t('engine_tip')} onChange=${(v) => save({ engine_mode: v })}
          options=${s.engines.map((e) => ({ value: e.value, label: t(e.key) }))} /></div>
      <div class="comment" data-testid="tr-times">${t('engine_times_info')}</div>
    <//>
    <${Group} title=${t('dialogue_style_group')}>
      <${Checkbox} testid="tr-dialogue" label=${t('dialogue_style_label')} tooltip=${t('dialogue_style_tip')} checked=${s.dialogue_style} onChange=${(v) => save({ dialogue_style: v })} />
    <//>
    ${s.show_cards ? html`<div class="profile-cards" data-testid="tr-cards">${s.cards.map((c) => html`
      <label class=${'profile-card' + (s.profile === c.value ? ' selected' : '')} data-profile=${c.value}>
        <input type="radio" name="profile" checked=${s.profile === c.value} onChange=${() => save({ profile: c.value })} />
        <div><div class="profile-name">${t(c.name_key)}${c.recommended ? html` <span class="badge">${t('recommended')}</span>` : null}</div>
          <div class="profile-desc">${t(c.desc_key)}</div><div class="profile-params">${c.params} · ${c.time}</div>
          ${c.warning_key ? html`<div class="profile-warn">${t(c.warning_key)}</div>` : null}</div></label>`)}</div>` : null}
  </div>`;
}

/** Il pulsante si blocca subito: la prima riga del sottoprocesso puo' arrivare solo dopo qualche secondo. */
function markRunning(job) {
  const env = getState().env;
  setState({ env: { ...env, [job]: { ...env[job], running: true, lines: [], last_line: '', exit_code: null } } });
}

// -------------------------------------------------------------------------------------------------------------------- Traduzione
function Section({ tone, title, radio, children, testid }) {
  return html`<div class="model-section" data-testid=${testid}>
    ${radio ? html`<input type="radio" class="model-radio" name="tmd-model" checked=${radio.checked} onChange=${radio.onChange} data-testid=${testid + '-radio'} />` : null}
    <div class=${'section-box tone-' + tone}><div class="section-title">${title}</div>${children}</div></div>`;
}

function Status({ ok, text, testid }) { return html`<div class=${'status-line ' + (ok ? 'ok' : 'warn')} data-testid=${testid}>${text}</div>`; }

export function TranslationPage({ active }) {
  const [s, setS] = useState(null);
  const [pick, setPick] = useState(null);                  // 'nllb_ft_path' | 'llm_path' | null: navigatore cartelle aperto
  const [ftPath, setFtPath] = useState(null);
  const [llmPath, setLlmPath] = useState(null);
  const env = useStore((st) => st.env);
  const [diarMsg, setDiarMsg] = useState('');
  const load = useCallback(async () => { const r = await get('/api/settings/translation'); if (r.ok) setS(r.data); return r.data; }, []);
  useEffect(() => { if (active) load(); }, [active]);
  useEffect(() => { if (s && ftPath === null) { setFtPath(s.nllb_ft.path); setLlmPath(s.llm_path); } }, [s]);
  if (!s) return null;
  if (!s.translator_available) return html`<div class="page page-translation"><div class="error-page" data-testid="tm-unavailable">${t('tmd_error_title') + '\n\n' + t('tmd_import_error')}</div></div>`;
  const upd = (r) => { if (r.ok) setS(r.data.state || r.data); return r; };
  const flag = async (key, value) => upd(await put('/api/settings/translation/flag', { key, value }));
  async function choose(name) {
    const r = await put('/api/settings/translation/model', { name });
    upd(r);
  }
  async function savePath(kind, value) {
    const r = upd(await put('/api/settings/translation/' + kind, { path: value }));
    if (!r.ok) return;
    const k = r.data.kind;
    if (k === 'empty') messageBox('warning', t('path_empty'), t('tmd_enter_merged_path'));
    else if (k === 'missing') messageBox('warning', t('folder_not_found'), t('tmd_folder_missing_msg', { path: value }));
    else if (k === 'invalid') messageBox('warning', t('folder_invalid'), t('tmd_folder_invalid_msg'));
    else { messageBox('info', t('path_saved_title'), t('path_saved_msg')); if (kind === 'nllb_ft_path') setFtPath(r.data.path); else setLlmPath(r.data.path); }
  }
  async function saveSecret(kind, value, emptyTitle, emptyMsg, invalidTitle, invalidMsg) {
    const r = upd(await put('/api/settings/translation/' + kind, { value }));
    if (!r.ok) return;
    if (r.data.kind === 'empty') messageBox('warning', emptyTitle, emptyMsg);
    else if (r.data.kind === 'invalid') messageBox('warning', invalidTitle, invalidMsg(r.data.error));
    else messageBox('info', t('creds_saved_title'), t('creds_saved_msg'));
  }
  async function saveOpenAi(key, model) {
    const r = upd(await put('/api/settings/translation/openai', { key, model }));
    if (!r.ok) return;
    if (r.data.kind === 'invalid') messageBox('warning', t('tmd_api_key_invalid_title'), r.data.error);
    else messageBox('info', t('creds_saved_title'), t('creds_saved_msg'));
  }
  async function download() {
    const r = await post('/api/settings/translation/llm_download');
    if (r.status === 409) messageBox('warning', t('tmd_token_missing_title'), t('tmd_save_hf_token_first'));
    else if (r.ok) markRunning('llm-download');
  }
  async function diarTest() {
    const r = await post('/api/settings/translation/diarization_test');
    if (r.status === 409) setDiarMsg(t('tmd_token_not_set_save_first'));
    else { setDiarMsg(t('tmd_diar_test_started')); if (r.ok) markRunning('diarization-test'); }
  }
  const model = s.model;
  const radio = (name) => ({ checked: model === name, onChange: () => choose(name) });
  const dl = env['llm-download'] || (s.jobs || {})['llm-download'] || {};
  const dt = env['diarization-test'] || (s.jobs || {})['diarization-test'] || {};
  const dlDone = dl.running === false && dl.exit_code !== null && dl.exit_code !== undefined;
  const diarLines = (dt.lines || []).filter((l) => !l.startsWith('⏳'));
  const diarText = dt.running ? (dt.last_line || diarMsg) : (dt.exit_code !== null && dt.exit_code !== undefined && dt.running === false
    ? (diarLines.length ? diarLines.slice(-4).join('\n') : t('tmd_no_test_output')) : diarMsg);
  const g = s.flags;
  const gm = s.gender_missing || [];
  return html`<div class="page page-translation">
    <div class="h1" data-testid="tm-header">${t('tmd_header')}</div><div class="lead">${t('tmd_subtitle')}</div>
    <${Section} tone="neutral" title="NLLB-200" radio=${radio('nllb')} testid="tm-nllb"><div class="body">${t('tmd_feat_nllb')}</div><//>
    <${Section} tone="green" title="NLLB-200 Fine-Tuned (Plex)" radio=${radio('nllb_finetuned')} testid="tm-nllbft">
      <div class="body">${t('tmd_feat_nllb_ft')}</div>
      <${Group} title=${t('model_folder_group')}>
        <div class="key-row"><${TextInput} testid="tm-ft-path" value=${ftPath} placeholder="C:\\...\\nllb-subtitles-lora\\merged_model" onCommit=${(v) => setFtPath(v)} />
          <button class="btn btn-primary btn-fixed" data-testid="tm-ft-browse" onClick=${() => setPick('nllb_ft_path')}>${t('browse')}</button></div>
        <button class="btn btn-primary" data-testid="tm-ft-save" onClick=${() => savePath('nllb_ft_path', document.querySelector('[data-testid=tm-ft-path]').value)}>${t('save_path')}</button>
      <//>
      <${Status} ok=${s.nllb_ft.configured} text=${s.nllb_ft.configured ? t('tmd_configured') : t('tmd_not_configured')} testid="tm-ft-status" />
    <//>
    <${Group} title=${t('nllb_params_group')} testid="tm-params">
      <div class="inline-row"><span>${t('nllb_num_beams_label')}</span>
        <${Spin} testid="tm-beams" value=${s.nllb_beams} min=${1} max=${20} tooltip=${t('nllb_num_beams_tooltip')}
          onChange=${async (v) => upd(await put('/api/settings/translation/nllb_beams', { value: v }))} /></div>
    <//>
    <${Section} tone="purple" title="LLM (Aya)" radio=${radio('llm')} testid="tm-llm">
      <div class="body">${t('tmd_feat_llm')}</div>
      <${Group} title=${t('model_folder_group')}>
        <div class="key-row"><${TextInput} testid="tm-llm-path" value=${llmPath} placeholder=${t('tmd_llm_path_placeholder')} onCommit=${(v) => setLlmPath(v)} />
          <button class="btn btn-primary btn-fixed" data-testid="tm-llm-browse" onClick=${() => setPick('llm_path')}>${t('browse')}</button></div>
        <button class="btn btn-primary" data-testid="tm-llm-save" onClick=${() => savePath('llm_path', document.querySelector('[data-testid=tm-llm-path]').value)}>${t('save_path')}</button>
      <//>
      <${Group} title=${t('hf_token_group')}>
        <div class="key-row"><${TextInput} testid="tm-hf" revealed=${false} placeholder=${s.hf_token_set ? '••••••••' : 'hf_...'} value="" onCommit=${() => {}} />
          <button class="btn btn-primary btn-fixed" data-testid="tm-hf-save" onClick=${() => saveSecret('hf_token', document.querySelector('[data-testid=tm-hf]').value, t('token_empty'), t('tmd_enter_valid_token'), t('tmd_token_invalid_title'), (e) => t('tmd_token_invalid_msg', { error: e }))}>${t('save_token')}</button></div>
      <//>
      <button class="btn btn-primary" data-testid="tm-llm-download" disabled=${!!dl.running} onClick=${download}>${t('download_llm_model')}</button>
      ${dl.running ? html`<div class="progress-line" data-testid="tm-llm-progress">${dl.last_line || ''}</div>` : null}
      ${dlDone ? html`<div class=${'status-line ' + (dl.exit_code === 0 ? 'ok' : 'warn')} data-testid="tm-llm-result">${dl.exit_code === 0 ? t('tmd_download_done') : '[X] ' + (dl.last_line || t('tmd_load_failed'))}</div>` : null}
    <//>
    <${Section} tone="blue" title="Claude API" radio=${radio('claude')} testid="tm-claude">
      <div class="body">${t('tmd_feat_claude')}</div>
      <div class="caption">${t('api_key_info_claude')}</div>
      <div class="key-row"><${TextInput} testid="tm-claude-key" revealed=${false} placeholder=${s.claude_key_set ? '••••••••' : 'sk-ant-...'} value="" onCommit=${() => {}} />
        <button class="btn btn-primary btn-fixed" data-testid="tm-claude-save" onClick=${() => saveSecret('claude_key', document.querySelector('[data-testid=tm-claude-key]').value, t('save_api_key'), t('tmd_enter_valid_api_key'), t('tmd_api_key_invalid_title'), (e) => t('tmd_api_key_invalid_msg', { error: e }))}>${t('save_api_key')}</button></div>
      <${Status} ok=${s.claude_key_set} text=${s.claude_key_set ? t('tmd_creds_configured') : t('tmd_not_configured')} testid="tm-claude-status" />
    <//>
    <${Section} tone="orange" title="OpenSubtitles" radio=${radio('opensubtitles')} testid="tm-os">
      <div class="body">${t('tmd_feat_os')}</div><div class="caption">${t('os_creds_info')}</div>
      <${Status} ok=${s.os_rest_configured} text=${s.os_rest_configured ? t('tmd_creds_configured') : t('tmd_creds_not_configured')} testid="tm-os-status" />
    <//>
    <${Section} tone="blue" title="OpenAI" radio=${radio('openai')} testid="tm-openai">
      <div class="body">${t('tmd_feat_openai')}</div>
      <div class="inline-row"><span>${t('tmd_model_label')}</span>
        <${Select} testid="tm-oai-model" value=${s.openai_model} onChange=${(v) => saveOpenAi('', v)} options=${s.openai_models.map((m) => ({ value: m, label: m }))} /></div>
      <div class="caption">${t('api_key_info_openai')}</div>
      <div class="key-row"><${TextInput} testid="tm-oai-key" revealed=${false} placeholder=${s.openai_key_set ? '••••••••' : 'sk-...'} value="" onCommit=${() => {}} />
        <button class="btn btn-primary btn-fixed" data-testid="tm-oai-save" onClick=${() => saveOpenAi(document.querySelector('[data-testid=tm-oai-key]').value, document.querySelector('[data-testid=tm-oai-model]').value)}>${t('save')}</button></div>
      <${Status} ok=${s.openai_key_set} text=${s.openai_key_set ? t('tmd_creds_configured') : t('tmd_not_configured')} testid="tm-oai-status" />
    <//>
    <${Section} tone="purple" title=${t('diarization_title')} testid="tm-diar-section">
      <div class="body">${t('diarization_desc')}</div>
      <${Group} title=${t('hf_token_label')}>
        <div class="key-row"><${TextInput} testid="tm-diar-token" revealed=${false} placeholder=${s.hf_token_set ? '••••••••' : 'hf_...'} value="" onCommit=${() => {}} />
          <button class="btn btn-primary btn-fixed" data-testid="tm-diar-save" onClick=${() => saveSecret('hf_token', document.querySelector('[data-testid=tm-diar-token]').value, t('token_empty'), t('tmd_enter_valid_token'), t('tmd_token_invalid_title'), (e) => e)}>${t('save')}</button></div>
        <div class="caption">${t('tmd_hf_token_howto', { urls: s.diarization_urls })}</div>
        <${Status} ok=${s.hf_token_set} text=${s.hf_token_set ? t('tmd_creds_configured') : t('tmd_not_configured')} testid="tm-diar-status" />
      <//>
      <button class="btn btn-primary" data-testid="tm-diar-test" disabled=${!!dt.running} onClick=${diarTest}>${t('test_download')}</button>
      <div class=${'caption diar-result' + (dt.exit_code === 0 ? ' ok' : dt.exit_code ? ' bad' : '')} data-testid="tm-diar-result">${diarText}</div>
      <${Checkbox} testid="tm-align" label=${t('forced_alignment_check')} tooltip=${t('tmd_align_tooltip')} checked=${g.enable_forced_alignment} onChange=${(v) => flag('enable_forced_alignment', v)} />
      <${Checkbox} testid="tm-diar" label=${t('diarization_check')} checked=${g.enable_diarization} onChange=${(v) => flag('enable_diarization', v)} />
      <div class="inline-row"><span class="fixed-label">${t('speakers_label')}</span>
        <${Spin} testid="tm-speakers" value=${g.diarization_num_speakers} min=${0} max=${10} special=${t('auto_speakers')} tooltip=${t('speakers_tip')}
          onChange=${(v) => flag('diarization_num_speakers', v)} /></div>
    <//>
    <${Section} tone="red" title=${t('tmd_gender_title')} testid="tm-gender">
      <div class="body">${t('tmd_gender_desc')}</div>
      <${Status} ok=${!gm.length} text=${gm.length ? gm.map((k) => t(k)).join(' — ') : t('tmd_gender_prereq_ok')} testid="tm-gender-status" />
      <${Checkbox} testid="tm-gender-enable" label=${t('tmd_gender_enable')} checked=${g.gender_correction_enabled} onChange=${(v) => flag('gender_correction_enabled', v)} />
      <${Checkbox} testid="tm-gender-p2" label=${t('tmd_gender_p2')} checked=${g.gender_correction_second_person} onChange=${(v) => flag('gender_correction_second_person', v)} />
      <div class="caption warn-italic">${t('tmd_gender_info')}</div>
    <//>
    <${Section} tone="blue" title=${t('force_audio_title')} testid="tm-force">
      <${Checkbox} testid="tm-force-audio" label=${t('force_audio_checkbox')} checked=${g.force_audio_transcription} onChange=${(v) => flag('force_audio_transcription', v)} />
      <div class="caption">${t('force_audio_info')}</div>
    <//>
    ${pick ? html`<${FileBrowser} mode="folder" title=${t('select_model_folder')} onCancel=${() => setPick(null)}
      onPick=${(paths) => { const k = pick; setPick(null); (k === 'nllb_ft_path' ? setFtPath : setLlmPath)(paths[0]); document.querySelector('[data-testid=' + (k === 'nllb_ft_path' ? 'tm-ft-path' : 'tm-llm-path') + ']').value = paths[0]; }} />` : null}
  </div>`;
}
