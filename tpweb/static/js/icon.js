import { html } from '/static/js/lib.js';
import { ICONS } from '/static/js/icons.js';

/** Icona della GUI Qt (stesso disegno): colore = `currentColor` del contenitore. */
export function Icon({ name, size = 14, class: cls = '' }) {
  const inner = ICONS[name] || '';
  return html`<svg class=${'icon ' + cls} width=${size} height=${size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" dangerouslySetInnerHTML=${{ __html: inner }}></svg>`;
}
