import { html, useState, useEffect, useRef, useLayoutEffect } from '/static/js/lib.js';
import { t } from '/static/js/i18n.js';
import { get, post, put } from '/static/js/api.js';
import { Icon } from '/static/js/icon.js';
import { Checkbox } from '/static/js/form.js';

/** Revisione mirata dell'OCR (OcrReviewDialog): gli eventi stanno sul server; qui lista, immagine, editor e comandi.
 *  Chiudere senza «Fatto» annulla il lavoro (Rejected), come la GUI. */
export function OcrReviewDialog() {
  const [list, setList] = useState(null);                  // {items, counter, first, total}
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const [cur, setCur] = useState(-1);
  const [ev, setEv] = useState(null);
  const [text, setText] = useState('');
  const area = useRef(null);
  const loaded = useRef(false);

  async function loadList(flag, keep) {
    const r = await get('/api/ocr/review/list?only_flagged=' + flag);
    if (r.ok) { setList(r.data); return r.data; }
    return null;
  }
  async function show(i) {
    const r = await get('/api/ocr/review/event/' + i);
    if (!r.ok) { setCur(-1); setEv(null); setText(''); return; }
    setCur(i); setEv(r.data); setText(r.data.text);
    setTimeout(() => area.current && area.current.focus(), 0);
  }
  useEffect(() => {                                        // all'apertura: primo evento dubbio, altrimenti il primo
    if (loaded.current) return;
    loaded.current = true;
    loadList(false).then((l) => { if (l && l.first !== null) show(l.first); });
  }, []);
  useLayoutEffect(() => {
    const k = (e) => { if (e.key === 'Escape' && document.querySelectorAll('.modal-backdrop').length < 2) finish(false); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  });

  async function save() {
    if (cur < 0 || !ev || text === ev.text) return;
    const r = await put('/api/ocr/review/text', { i: cur, text });
    if (r.ok) { setEv({ ...ev, text }); setList((l) => l && { ...l, counter: r.data.counter, items: l.items.map((it) => (it.i === cur ? { ...it, label: r.data.label } : it)) }); }
  }
  async function select(i) {
    await save();
    const wasVisible = list.items.some((it) => it.i === i);
    if (!wasVisible && onlyFlagged) { setOnlyFlagged(false); await loadList(false); }      // evento filtrato fuori: si disattiva il filtro
    await show(i);
  }
  async function toggleFilter(v) {
    await save();
    setOnlyFlagged(v);
    const l = await loadList(v);
    if (l && !l.items.some((it) => it.i === cur)) { if (l.items.length) show(l.items[0].i); else { setCur(-1); setEv(null); setText(''); } }
  }
  async function enterSave() {                              // Invio: salva e salta al prossimo dubbio
    await save();
    const r = await get('/api/ocr/review/next-flagged?i=' + cur);
    if (r.ok && r.data.next !== null && r.data.next !== cur) select(r.data.next);
  }
  async function verify() {
    if (cur < 0) return;
    const r = await post('/api/ocr/review/verify', { i: cur, text });
    if (!r.ok) return;
    setEv({ ...ev, text });
    setList((l) => l && { ...l, counter: r.data.counter, items: l.items.map((it) => (it.i === cur ? { ...it, label: r.data.label } : it)) });
    if (r.data.next !== null && r.data.next !== cur) await select(r.data.next);
    else if (onlyFlagged) await loadList(true);
    else await show(cur);
  }
  async function italic() {
    const el = area.current;
    const sel = el && el.selectionStart !== el.selectionEnd ? [el.selectionStart, el.selectionEnd] : null;
    const r = await post('/api/ocr/review/italic', { text, sel });
    if (!r.ok) return;
    setText(r.data.text);
    if (r.data.sel) setTimeout(() => { if (area.current) area.current.setSelectionRange(r.data.sel[0], r.data.sel[1]); }, 0);
  }
  async function finish(accept) {
    if (accept) await save();
    await post('/api/ocr/review/done', { accept });
  }
  const key = (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey) { e.preventDefault(); enterSave(); }       // Maiusc/Ctrl+Invio: riga nuova
  };

  return html`<div class="modal-backdrop">
    <div class="tool-dialog review-dialog" role="dialog" aria-modal="true" data-testid="ocr-review" onClick=${(e) => e.stopPropagation()}>
      <div class="settings-header"><span class="settings-title">${t('ocr_review_title')}</span>
        <button class="tool-btn" data-testid="rv-close" title=${t('web_close')} onClick=${() => finish(false)}>✕</button></div>
      <div class="tool-body">
        <div class="note review-instruction">${t('ocr_review_instruction')}</div>
        <div class="review-cols">
          <div class="review-left">
            <${Checkbox} testid="rv-flagged" label=${t('ocr_only_flagged')} checked=${onlyFlagged} onChange=${toggleFilter} />
            <div class="review-list" data-testid="rv-list">${list ? list.items.map((it) => html`<div key=${it.i} data-i=${it.i}
              class=${'review-item' + (it.i === cur ? ' selected' : '')} onClick=${() => select(it.i)}>${it.label}</div>`) : null}</div>
            <div class="caption" data-testid="rv-counter">${list ? list.counter : ''}</div>
          </div>
          <div class="review-right">
            <div class="caption" data-testid="rv-info">${ev ? ev.info : ''}</div>
            <div class="review-image">${ev && ev.has_image ? html`<img data-testid="rv-image" src=${'/api/ocr/review/image/' + cur} alt="" />`
              : html`<span class="muted-small" data-testid="rv-noimage">${t('ocr_no_image')}</span>`}</div>
            <span>${t('ocr_text_label')}</span>
            <textarea class="input review-text" data-testid="rv-text" ref=${area} disabled=${!ev} value=${text}
              onInput=${(e) => setText(e.target.value)} onKeyDown=${key}></textarea>
            <div class="btn-row">
              <button class="btn btn-primary" data-testid="rv-italic" title=${t('ocr_toggle_italic_tip')} disabled=${!ev} onClick=${italic}>${t('ocr_toggle_italic')}</button>
              <span class="grow"></span>
              <button class="btn btn-primary" data-testid="rv-prev" disabled=${!ev || !ev.can_prev} onClick=${() => select(cur - 1)}>${t('ocr_prev')}</button>
              <button class="btn btn-primary" data-testid="rv-next" disabled=${!ev || !ev.can_next} onClick=${() => select(cur + 1)}>${t('ocr_next')}</button>
              <button class="btn btn-start" data-testid="rv-verify" title=${t('ocr_verified_tip')} disabled=${!ev} onClick=${verify}>${t('ocr_verified')}</button>
            </div>
          </div>
        </div>
        <div class="btn-row end"><button class="btn btn-start" data-testid="rv-done" style=${{ flex: '0 0 160px' }} onClick=${() => finish(true)}>${t('ocr_done')}</button></div>
      </div>
    </div></div>`;
}
