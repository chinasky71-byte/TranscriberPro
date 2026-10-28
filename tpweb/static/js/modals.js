import { html, useState, useEffect, useLayoutEffect } from '/static/js/lib.js';
import { get, post } from '/static/js/api.js';
import { t } from '/static/js/i18n.js';
import { Icon } from '/static/js/icon.js';

/** Conferma: stesso schema dei QMessageBox della GUI (titolo + testo, «Si'»/«No», predefinito No). */
export function Confirm({ title, text, onYes, onNo }) {
  useLayoutEffect(() => {      // Esc attivo appena la finestra compare (prima del primo disegno)
    const k = (e) => { if (e.key === 'Escape') onNo(); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, []);
  return html`<div class="modal-backdrop" onClick=${onNo}>
    <div class="modal modal-confirm" role="dialog" aria-modal="true" onClick=${(e) => e.stopPropagation()}>
      <div class="modal-title">${title}</div>
      <div class="modal-text">${text}</div>
      <div class="modal-actions">
        <button class="btn btn-primary" data-testid="confirm-yes" onClick=${onYes}>${t('web_yes')}</button>
        <button class="btn btn-primary" autofocus data-testid="confirm-no" onClick=${onNo}>${t('web_no')}</button>
      </div>
    </div></div>`;
}


/** Navigatore del file system al posto dei dialoghi nativi (con il guscio nativo di pywebview si useranno quelli veri). */
export function FileBrowser({ mode, title, exts, onPick, onCancel }) {
  const [roots, setRoots] = useState([]);
  const [cur, setCur] = useState(null);       // {path, parent, dirs, files}
  const [err, setErr] = useState('');
  const [sel, setSel] = useState([]);
  const [last, setLast] = useState(null);

  async function open(path) {
    const q = '/api/fs/list?path=' + encodeURIComponent(path) + (mode === 'files' ? (exts ? '&exts=' + encodeURIComponent(exts.join(',')) : '') : '&dirs_only=true');
    const r = await get(q);
    if (r.ok) { setCur(r.data); setErr(''); setSel([]); setLast(null); }
    else setErr(t('web_fs_error', { error: (r.data && r.data.error) || r.status }));
  }
  useEffect(() => {
    (async () => {
      const r = await get('/api/fs/roots');
      if (r.ok) { setRoots(r.data.roots); open(r.data.last || r.data.roots[0].path); }
    })();
    const k = (e) => { if (e.key === 'Escape') onCancel(); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, []);

  const files = cur ? cur.files : [];
  function clickFile(f, e) {
    if (e.shiftKey && last !== null) {
      const a = files.findIndex((x) => x.path === last), b = files.findIndex((x) => x.path === f.path);
      const [lo, hi] = a < b ? [a, b] : [b, a];
      setSel(files.slice(lo, hi + 1).map((x) => x.path));
    } else if (e.ctrlKey || e.metaKey) {
      setSel(sel.includes(f.path) ? sel.filter((p) => p !== f.path) : [...sel, f.path]);
      setLast(f.path);
    } else { setSel([f.path]); setLast(f.path); }
  }
  async function confirm() {
    if (mode === 'folder') await post('/api/fs/last', { folder: cur.path });
    else if (sel.length) await post('/api/fs/last', { folder: cur.path });
    onPick(mode === 'folder' ? [cur.path] : sel);
  }

  return html`<div class="modal-backdrop" onClick=${onCancel}>
    <div class="modal modal-fs" role="dialog" aria-modal="true" data-testid="file-browser" onClick=${(e) => e.stopPropagation()}>
      <div class="modal-title">${title}</div>
      <div class="fs-body">
        <div class="fs-places"><div class="fs-places-title">${t('web_fs_places')}</div>
          ${roots.map((r) => html`<button class="fs-place" onClick=${() => open(r.path)} title=${r.path}>${r.name}</button>`)}
        </div>
        <div class="fs-main">
          <div class="fs-pathbar">
            <button class="btn btn-primary fs-up" disabled=${!cur || !cur.parent} onClick=${() => open(cur.parent)} title=${t('web_fs_up')}>↑</button>
            <div class="fs-path" data-testid="fs-path">${cur ? cur.path : ''}</div>
          </div>
          ${err ? html`<div class="fs-error">${err}</div>` : null}
          <div class="fs-list" data-testid="fs-list">
            ${cur && cur.dirs.map((d) => html`<div class="fs-row fs-dir" onDblClick=${() => open(d.path)} onClick=${() => open(d.path)}>
              <${Icon} name="folder" size=${14} /><span class="fs-name">${d.name}</span></div>`)}
            ${files.map((f) => html`<div class=${'fs-row fs-file' + (sel.includes(f.path) ? ' selected' : '')} data-path=${f.path}
                onClick=${(e) => clickFile(f, e)}><${Icon} name="film" size=${14} /><span class="fs-name">${f.name}</span><span class="fs-size">${f.size}</span></div>`)}
            ${cur && !cur.dirs.length && !files.length ? html`<div class="fs-empty">${t('web_fs_empty')}</div>` : null}
          </div>
        </div>
      </div>
      <div class="modal-actions">
        <button class="btn btn-start" data-testid="fs-ok" disabled=${mode === 'files' && !sel.length} onClick=${confirm}>
          ${mode === 'folder' ? t('web_fs_select_here') : t('web_fs_add') + (sel.length ? ' (' + sel.length + ')' : '')}</button>
        <button class="btn btn-primary" data-testid="fs-cancel" onClick=${onCancel}>${t('web_cancel')}</button>
      </div>
    </div></div>`;
}
