import { html, render, useState, useEffect, useRef } from '/static/js/lib.js';
import { get, put } from '/static/js/api.js';
import { loadTexts, t } from '/static/js/i18n.js';
import { connect, startPolling, refreshQueue, refreshJob, refreshHistoryCount, setState, useStore, addPaths } from '/static/js/store.js';
import { TitleBar, TabBar } from '/static/js/chrome.js';
import { QueuePanel } from '/static/js/queue_panel.js';
import { CenterPanel, RightPanel } from '/static/js/side_panels.js';
import { HistoryView } from '/static/js/history_view.js';
import { SettingsDialog } from '/static/js/settings.js';
import { MessageHost } from '/static/js/dialogs.js';
import { GlossaryDialog } from '/static/js/tools_glossary.js';
import { SyncDialog } from '/static/js/tools_sync.js';
import { OcrReviewDialog } from '/static/js/ocr_review.js';

/** Trascinamento di file da Esplorer (come dropEvent della GUI): il guscio nativo da' il percorso vero in `pywebviewFullPath`;
 *  in un browser i percorsi non esistono e il rilascio e' ignorato (ma non apre il file al posto della pagina). */
function onDragOver(e) { e.preventDefault(); }
function onDrop(e) {
  e.preventDefault();
  const paths = [...((e.dataTransfer && e.dataTransfer.files) || [])].map((f) => f.pywebviewFullPath).filter(Boolean);
  if (paths.length) addPaths(paths);
}

const MIN_PANEL = 200;
const DEFAULT_SIZES = [414, 472, 472];                  // 2:3:3 alla larghezza 1400 della finestra Qt di riferimento

/** QSplitter a tre colonne: le maniglie spostano il confine tra due pannelli vicini (minimo 200 px); la misura si salva a fine trascinamento. */
function SplitRow() {
  const [sizes, setSizes] = useState(DEFAULT_SIZES);
  const ref = useRef(null);
  useEffect(() => { get('/api/settings/splitter').then((r) => { if (r.ok && r.data.sizes) setSizes(r.data.sizes); }); }, []);
  function drag(i, e) {
    e.preventDefault();
    const total = ref.current.clientWidth - 12;          // le due maniglie da 6 px
    const sum = sizes.reduce((a, b) => a + b, 0);
    const px = sizes.map((x) => (x / sum) * total);
    const x0 = e.clientX, start = px.slice();
    let latest = sizes;
    const move = (ev) => {
      const dx = Math.max(MIN_PANEL - start[i], Math.min(start[i + 1] - MIN_PANEL, ev.clientX - x0));
      const next = start.slice();
      next[i] = start[i] + dx;
      next[i + 1] = start[i + 1] - dx;
      latest = next.map((v) => Math.round(v));
      setSizes(latest);
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      put('/api/settings/splitter', { sizes: latest });
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  }
  return html`<div class="splitter" ref=${ref} style=${{ gridTemplateColumns: `${sizes[0]}fr 6px ${sizes[1]}fr 6px ${sizes[2]}fr` }}>
    <${QueuePanel} /><div class="split-handle" data-testid="split-handle-0" onPointerDown=${(e) => drag(0, e)}></div>
    <${CenterPanel} /><div class="split-handle" data-testid="split-handle-1" onPointerDown=${(e) => drag(1, e)}></div><${RightPanel} />
  </div>`;
}

function App() {
  const tab = useStore((s) => s.ui.tab);
  const settingsOpen = useStore((s) => !!s.ui.settings);
  const tool = useStore((s) => s.ui.tool);
  const reviewing = useStore((s) => s.ocr.review);
  return html`<div class="window" onDragOver=${onDragOver} onDrop=${onDrop}>
    <${TitleBar} />
    <${TabBar} />
    <main class="stack">
      ${tab === 'queue'
        ? html`<${SplitRow} />`
        : html`<div class="history-wrap"><${HistoryView} onCount=${(n) => setState({ historyCount: n })} /></div>`}
    </main>
    ${settingsOpen ? html`<${SettingsDialog} />` : null}
    ${tool === 'glossary' ? html`<${GlossaryDialog} />` : null}
    ${tool === 'sync' ? html`<${SyncDialog} />` : null}
    ${reviewing ? html`<${OcrReviewDialog} />` : null}
    <${MessageHost} />
  </div>`;
}

(async () => {
  await loadTexts();
  document.title = t('window_title');
  render(html`<${App} />`, document.getElementById('app'));
  connect();
  refreshQueue();
  refreshJob();
  refreshHistoryCount();
  startPolling();
})();
