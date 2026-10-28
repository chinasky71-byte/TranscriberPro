import { html, useState, useLayoutEffect, useRef } from '/static/js/lib.js';

/** Menu contestuale con sottomenu (come QMenu). items: [{label, onClick, checked?, disabled?, separator?, children?}]. */
export function ContextMenu({ x, y, items, onClose }) {
  const ref = useRef(null);
  const [open, setOpen] = useState(null);
  const [pos, setPos] = useState({ x, y });
  useLayoutEffect(() => {
    const r = ref.current.getBoundingClientRect();
    setPos({ x: Math.max(0, Math.min(x, window.innerWidth - r.width - 4)), y: Math.max(0, Math.min(y, window.innerHeight - r.height - 4)) });
    const key = (e) => { if (e.key === 'Escape') onClose(); };
    const away = (e) => { if (!e.target.closest('.ctx-menu')) onClose(); };
    window.addEventListener('keydown', key);
    window.addEventListener('mousedown', away, true);
    window.addEventListener('blur', onClose);
    return () => { window.removeEventListener('keydown', key); window.removeEventListener('mousedown', away, true); window.removeEventListener('blur', onClose); };
  }, []);
  const entry = (it, i) => {
    if (it.separator) return html`<div class="ctx-sep" key=${i}></div>`;
    const sub = it.children ? html`<${Sub} items=${it.children} onClose=${onClose} />` : null;
    return html`<div key=${i} class=${'ctx-item' + (it.disabled ? ' disabled' : '') + (it.children ? ' has-sub' : '') + (open === i ? ' open' : '')}
        role="menuitem" data-label=${it.label} onMouseEnter=${() => setOpen(it.children ? i : null)}
        onClick=${(e) => { e.stopPropagation(); if (it.disabled || it.children) return; onClose(); it.onClick(); }}>
      <span class="ctx-check">${it.checked ? '✓' : ''}</span><span class="ctx-label">${it.label}</span>${it.children ? html`<span class="ctx-arrow">›</span>` : null}
      ${open === i ? sub : null}</div>`;
  };
  return html`<div class="ctx-menu" ref=${ref} role="menu" data-testid="context-menu" style=${{ left: pos.x + 'px', top: pos.y + 'px' }}
      onContextMenu=${(e) => e.preventDefault()}>${items.map(entry)}</div>`;
}

function Sub({ items, onClose }) {
  return html`<div class="ctx-menu ctx-sub" role="menu">${items.map((it, i) => it.separator ? html`<div class="ctx-sep" key=${i}></div>` : html`
    <div key=${i} class=${'ctx-item' + (it.disabled ? ' disabled' : '')} role="menuitemcheckbox" aria-checked=${!!it.checked} data-label=${it.label}
        onClick=${(e) => { e.stopPropagation(); if (it.disabled) return; onClose(); it.onClick(); }}>
      <span class="ctx-check">${it.checked ? '✓' : ''}</span><span class="ctx-label">${it.label}</span></div>`)}</div>`;
}
