import { html, useState, useLayoutEffect } from '/static/js/lib.js';
import { t } from '/static/js/i18n.js';
import { Icon } from '/static/js/icon.js';
import { useStore, setUi, openSettings, openTool } from '/static/js/store.js';
import { post } from '/static/js/api.js';
import { Confirm } from '/static/js/modals.js';
import { ContextMenu } from '/static/js/context_menu.js';

export function TitleBar() {
  const running = useStore((s) => s.queue.running);
  const connected = useStore((s) => s.connected);
  const [quitAsk, setQuitAsk] = useState(false);
  const [toolsMenu, setToolsMenu] = useState(null);
  async function quit(force) {
    const r = await post('/api/quit', { force });
    if (r.status === 409) setQuitAsk(true);
    else if (r.ok) document.body.classList.add('closed');
  }
  return html`<header class="titlebar" data-testid="titlebar">
    <div class="brand"><span class="brand-mark">◈</span><span class="brand-name">Transcriber Pro</span><span class="brand-sep"></span>
      <span class="brand-sub">${t('web_brand_subtitle')}</span></div>
    <span class="grow"></span>
    <div class="status-pill"><span class=${'status-dot' + (running ? ' busy' : '')}></span><span class="status-label" data-testid="status">${!connected ? t('web_connection_lost') : (running ? t('mw_status_processing') : t('mw_status_ready'))}</span></div>
    <span class="grow"></span>
    <div class="title-actions">
      <button class="tool-btn" data-testid="tools-menu" title=${t('tools_menu')} disabled=${running}
        onClick=${(e) => { const r = e.currentTarget.getBoundingClientRect(); setToolsMenu({ x: r.left, y: r.bottom + 4 }); }}><${Icon} name="wrench" size=${16} /></button>
      <button class="tool-btn" data-testid="open-sync" title=${t('sync_dialog_title')} disabled=${running} onClick=${() => openTool('sync')}><${Icon} name="sync" size=${16} /></button>
      <button class="tool-btn" data-testid="open-settings" title=${t('settings_dialog_title')} onClick=${() => openSettings()}><${Icon} name="settings" size=${16} /></button>
      <button class="tool-btn" data-testid="quit" title=${t('web_quit')} onClick=${() => quit(false)}><${Icon} name="power" size=${16} /></button>
    </div>
    ${toolsMenu ? html`<${ContextMenu} x=${toolsMenu.x} y=${toolsMenu.y} onClose=${() => setToolsMenu(null)}
        items=${[{ label: t('tools_glossary'), onClick: () => openTool('glossary') }]} />` : null}
    ${quitAsk ? html`<${Confirm} title=${t('web_quit')} text=${t('web_quit_busy')} onNo=${() => setQuitAsk(false)}
        onYes=${() => { setQuitAsk(false); quit(true); }} />` : null}
  </header>`;
}

export function TabBar() {
  const tab = useStore((s) => s.ui.tab);
  const historyCount = useStore((s) => s.historyCount);
  const counts = useStore((s) => s.queue.counts);
  const gpu = useStore((s) => s.gpu);
  const [badgeX, setBadgeX] = useState(null);
  const active = counts.queued + counts.processing;
  // il badge sta al centro della pill di stato (come in Qt); si rimisura quando cambiano finestra o testo
  useLayoutEffect(() => {
    const place = () => {
      const pill = document.querySelector('.status-pill');
      const bar = document.querySelector('[data-testid=tabbar]');
      if (pill && bar) { const p = pill.getBoundingClientRect(), b = bar.getBoundingClientRect(); setBadgeX(p.left + p.width / 2 - b.left); }
    };
    place();
    window.addEventListener('resize', place);
    const pill = document.querySelector('.status-pill');
    const ro = new ResizeObserver(place);                       // la pill cambia larghezza col testo («Pronto» / «In elaborazione»)
    if (pill) ro.observe(pill);
    return () => { window.removeEventListener('resize', place); ro.disconnect(); };
  }, [gpu]);
  return html`<nav class="tabbar" data-testid="tabbar">
    <button class=${'tab' + (tab === 'queue' ? ' selected' : '')} data-tab="queue" onClick=${() => setUi({ tab: 'queue' })}>
      <${Icon} name="list" size=${15} class="ico-muted" />${active ? t('tab_queue') + '  (' + active + ')' : t('tab_queue')}</button>
    <button class=${'tab' + (tab === 'history' ? ' selected' : '')} data-tab="history" onClick=${() => setUi({ tab: 'history' })}>
      <${Icon} name="history" size=${15} class="ico-muted" />${historyCount ? t('tab_history') + '  (' + historyCount + ')' : t('tab_history')}</button>
    ${gpu ? html`<span class=${'gpu-badge ' + gpu.vendor} data-testid="gpu-badge" style=${{ left: (badgeX === null ? 700 : badgeX) + 'px' }}
        title=${gpu.vendor === 'cpu' ? t('gpu_badge_cpu_tip') : t('gpu_badge_tip', { name: gpu.text })}>${gpu.text}</span>` : null}
  </nav>`;
}
