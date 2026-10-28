import { html, useState } from '/static/js/lib.js';
import { t } from '/static/js/i18n.js';
import { Icon } from '/static/js/icon.js';
import { useStore, setUi } from '/static/js/store.js';
import { post } from '/static/js/api.js';
import { Confirm } from '/static/js/modals.js';

export function TitleBar() {
  const running = useStore((s) => s.queue.running);
  const connected = useStore((s) => s.connected);
  const [quitAsk, setQuitAsk] = useState(false);
  async function quit(force) {
    const r = await post('/api/quit', { force });
    if (r.status === 409) setQuitAsk(true);
    else if (r.ok) document.body.classList.add('closed');
  }
  return html`<header class="titlebar" data-testid="titlebar">
    <div class="brand"><span class="brand-mark">◈</span><span class="brand-name">Transcriber Pro</span><span class="brand-sep"></span>
      <span class="brand-sub">${t('web_brand_subtitle')}</span></div>
    <span class="grow"></span>
    <div class="status-pill"><span class=${'status-dot' + (running ? ' busy' : '')}></span><span class="status-label" data-testid="status">${connected ? t('mw_status_ready') : t('web_connection_lost')}</span></div>
    <span class="grow"></span>
    <div class="title-actions">
      <button class="tool-btn" title=${t('tools_menu')}><${Icon} name="wrench" size=${16} /></button>
      <button class="tool-btn" title=${t('sync_dialog_title')}><${Icon} name="sync" size=${16} /></button>
      <button class="tool-btn" title=${t('settings_dialog_title')}><${Icon} name="settings" size=${16} /></button>
      <button class="tool-btn" data-testid="quit" title=${t('web_quit')} onClick=${() => quit(false)}><${Icon} name="power" size=${16} /></button>
    </div>
    ${quitAsk ? html`<${Confirm} title=${t('web_quit')} text=${t('web_quit_busy')} onNo=${() => setQuitAsk(false)}
        onYes=${() => { setQuitAsk(false); quit(true); }} />` : null}
  </header>`;
}

export function TabBar() {
  const tab = useStore((s) => s.ui.tab);
  const historyCount = useStore((s) => s.historyCount);
  const total = useStore((s) => s.queue.rows.length);
  return html`<nav class="tabbar" data-testid="tabbar">
    <button class=${'tab' + (tab === 'queue' ? ' selected' : '')} data-tab="queue" onClick=${() => setUi({ tab: 'queue' })}>
      <${Icon} name="list" size=${15} class="ico-muted" />${t('tab_queue')} (${total})</button>
    <button class=${'tab' + (tab === 'history' ? ' selected' : '')} data-tab="history" onClick=${() => setUi({ tab: 'history' })}>
      <${Icon} name="history" size=${15} class="ico-muted" />${t('tab_history')}${historyCount === null ? '' : ' (' + historyCount + ')'}</button>
  </nav>`;
}
