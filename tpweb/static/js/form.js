import { html, useState, useEffect, useRef } from '/static/js/lib.js';
import { Icon } from '/static/js/icon.js';

/** QGroupBox: scheda con il titolo dentro (come il tema Qt). */
export function Group({ title, children, class: cls = '', testid }) {
  return html`<section class=${'group ' + cls} data-testid=${testid}><div class="group-title">${title}</div>${children}</section>`;
}

export function Row({ label, children, tooltip }) {
  return html`<div class="form-row" title=${tooltip}><label class="form-label">${label}</label><div class="form-field">${children}</div></div>`;
}

/** Campo di testo che SALVA quando perde il fuoco o su Invio (editingFinished di Qt). Si riallinea al valore del server. */
export function TextInput({ value, onCommit, placeholder, type = 'text', testid, tooltip, disabled, revealed }) {
  const [text, setText] = useState(value || '');
  const dirty = useRef(false);
  useEffect(() => { if (!dirty.current) setText(value || ''); }, [value]);
  const commit = () => { if (dirty.current) { dirty.current = false; onCommit(text); } };
  return html`<input class="input" type=${revealed === undefined ? type : (revealed ? 'text' : 'password')} value=${text} placeholder=${placeholder} data-testid=${testid}
    title=${tooltip} disabled=${disabled}
    onInput=${(e) => { dirty.current = true; setText(e.target.value); }} onBlur=${commit}
    onKeyDown=${(e) => { if (e.key === 'Enter') { e.preventDefault(); commit(); } }} />`;
}

export function TextArea({ value, onChange, placeholder, tooltip, testid, height = 64 }) {
  const [text, setText] = useState(value || '');
  const mine = useRef(false);
  useEffect(() => { if (!mine.current) setText(value || ''); }, [value]);
  return html`<textarea class="input textarea" style=${{ height: height + 'px' }} value=${text} placeholder=${placeholder} title=${tooltip} data-testid=${testid}
    onInput=${(e) => { mine.current = true; setText(e.target.value); onChange(e.target.value); }}></textarea>`;
}

export function Checkbox({ checked, onChange, label, tooltip, testid, disabled }) {
  return html`<label class=${'check' + (disabled ? ' disabled' : '')} title=${tooltip}>
    <input type="checkbox" checked=${!!checked} disabled=${disabled} data-testid=${testid} onChange=${(e) => onChange(e.target.checked)} />
    <span class="box"></span><span>${label}</span></label>`;
}

export function Radio({ checked, onChange, name, testid, children }) {
  return html`<label class="radio"><input type="radio" name=${name} checked=${!!checked} data-testid=${testid} onChange=${() => onChange()} />
    <span class="dotbox"></span>${children}</label>`;
}

export function Select({ value, options, onChange, testid, tooltip, disabled }) {
  return html`<span class="select-wrap"><select class="select" value=${value} data-testid=${testid} title=${tooltip} disabled=${disabled}
      onChange=${(e) => onChange(e.target.value)}>
    ${options.map((o) => html`<option value=${o.value} selected=${String(o.value) === String(value)} title=${o.tooltip}>${o.label}</option>`)}</select>
    <${Icon} name="chevDown" size=${12} class="select-chev" /></span>`;
}

/** QSpinBox / QDoubleSpinBox: salva a ogni cambio (`onChange`) o col pulsante (`onChange` solo aggiorna il modulo). */
export function Spin({ value, min, max, step = 1, decimals = 0, special, suffix = '', onChange, testid, tooltip, disabled }) {
  const shown = special !== undefined && Number(value) === min ? special : Number(value).toFixed(decimals) + suffix;
  const set = (v) => { const c = Math.max(min, Math.min(max, +v.toFixed(decimals))); if (c !== Number(value)) onChange(c); };
  return html`<span class=${'spin' + (disabled ? ' disabled' : '')} title=${tooltip}>
    <input class="input spin-input" data-testid=${testid} data-value=${value} value=${shown} disabled=${disabled}
      onChange=${(e) => { const n = parseFloat(String(e.target.value).replace(',', '.')); if (!Number.isNaN(n)) set(n); else e.target.value = shown; }}
      onKeyDown=${(e) => { if (e.key === 'ArrowUp') { e.preventDefault(); set(Number(value) + step); } if (e.key === 'ArrowDown') { e.preventDefault(); set(Number(value) - step); } }} />
    <button type="button" class="spin-btn up" tabindex="-1" disabled=${disabled} onClick=${() => set(Number(value) + step)}><${Icon} name="chevDown" size=${10} class="flip" /></button>
    <button type="button" class="spin-btn down" tabindex="-1" disabled=${disabled} onClick=${() => set(Number(value) - step)}><${Icon} name="chevDown" size=${10} /></button></span>`;
}
