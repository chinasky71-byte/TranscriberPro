import { html, useState, useEffect, useLayoutEffect } from '/static/js/lib.js';
import { t } from '/static/js/i18n.js';
import { get, put } from '/static/js/api.js';
import { Icon } from '/static/js/icon.js';
import { useStore, closeSettings, setUi, refreshJob } from '/static/js/store.js';
import { GeneralPage, JobsPage, BatchPage, OpenSubtitlesPage, OcrPage } from '/static/js/settings_basic.js';
import { TranscriptionPage, TranslationPage } from '/static/js/settings_models.js';

const TABS = [['general', 'wrench', 'settings_tab_general'], ['jobs', 'list', 'settings_tab_jobs'], ['transcription', 'mic', 'settings_tab_transcription'],
  ['translation', 'globe', 'settings_tab_translation'], ['batch', 'target', 'settings_tab_batch'], ['opensubtitles', 'cloud', 'settings_tab_opensubtitles'],
  ['ocr', 'caption', 'ocr_section_title']];
const PAGES = { general: GeneralPage, jobs: JobsPage, transcription: TranscriptionPage, translation: TranslationPage, batch: BatchPage,
  opensubtitles: OpenSubtitlesPage, ocr: OcrPage };

/** Impostazioni: barra laterale + pagina (le pagine si costruiscono alla prima visita). Si chiude con Esc o fuori dalla finestra. */
export function SettingsDialog() {
  const st = useStore((s) => s.ui.settings);
  const [tab, setTab] = useState(st && st.tab ? st.tab : null);
  const [built, setBuilt] = useState({});
  useEffect(() => {
    if (st && st.tab) { select(st.tab, false); return; }
    get('/api/settings').then((r) => select(r.ok && PAGES[r.data.last_tab] ? r.data.last_tab : 'general', false));   // come la GUI: riapre l'ultima scheda visitata
  }, []);
  useEffect(() => {
    const k = (e) => { if (e.key === 'Escape' && document.querySelectorAll('.modal-backdrop').length < 2) closeSettings(); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, []);
  function select(id, persist) {
    setTab(id);
    setBuilt((b) => ({ ...b, [id]: true }));
    if (persist) put('/api/settings/last_tab', { tab: id });
  }
  const go = (id) => select(id, true);
  const close = () => { closeSettings(); refreshJob(); };
  return html`<div class="modal-backdrop" onClick=${close}>
    <div class="settings-dialog" role="dialog" aria-modal="true" data-testid="settings-dialog" onClick=${(e) => e.stopPropagation()}>
      <div class="settings-header"><span class="settings-title">${t('settings_dialog_title')}</span>
        <button class="tool-btn" data-testid="settings-close" title=${t('web_close')} onClick=${close}><${Icon} name="x" size=${14} /></button></div>
      <div class="settings-body">
        <nav class="settings-sidebar" data-testid="settings-sidebar">
          ${TABS.map(([id, icon, label]) => html`<button class=${'side-item' + (tab === id ? ' selected' : '')} data-tab=${id} onClick=${() => go(id)}>
            <${Icon} name=${icon} size=${16} class="ico-muted" /><span>${t(label)}</span></button>`)}
        </nav>
        <div class="settings-content">
          ${TABS.map(([id]) => built[id] || tab === id ? html`<div class=${'settings-page' + (tab === id ? '' : ' hidden')} data-page=${id} key=${id}>
            ${(() => { const P = PAGES[id]; return html`<${P} active=${tab === id} go=${go} />`; })()}</div>` : null)}
        </div>
      </div>
    </div></div>`;
}
