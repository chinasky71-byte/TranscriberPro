import { html, useEffect } from '/static/js/lib.js';
import { t } from '/static/js/i18n.js';
import { useStore, setState } from '/static/js/store.js';

/** QMessageBox informativo / di avviso / di errore: un titolo, un testo e «OK». Si apre da qualsiasi punto con `messageBox`. */
export function messageBox(kind, title, text) {
  setState({ message: { kind, title, text } });
}

export function MessageHost() {
  const m = useStore((s) => s.message);
  const close = () => setState({ message: null });
  useEffect(() => {
    if (!m) return undefined;
    const k = (e) => { if (e.key === 'Escape' || e.key === 'Enter') { e.stopPropagation(); close(); } };
    window.addEventListener('keydown', k, true);
    return () => window.removeEventListener('keydown', k, true);
  }, [m]);
  if (!m) return null;
  const icon = { warning: '⚠️', error: '❌', info: 'ℹ️' }[m.kind] || '';
  return html`<div class="modal-backdrop msg-backdrop" onClick=${close}>
    <div class=${'modal modal-message kind-' + m.kind} role="alertdialog" aria-modal="true" data-testid="message-box" onClick=${(e) => e.stopPropagation()}>
      <div class="modal-title">${m.title}</div>
      <div class="modal-text"><span class="msg-icon">${icon}</span><span data-testid="message-text">${m.text}</span></div>
      <div class="modal-actions"><button class="btn btn-start" autofocus data-testid="message-ok" onClick=${close}>${t('web_ok')}</button></div>
    </div></div>`;
}
