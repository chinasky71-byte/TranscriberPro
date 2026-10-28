import { html, render, useState, useEffect } from '/static/js/lib.js';
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
        ? html`<div class="splitter"><${QueuePanel} /><${CenterPanel} /><${RightPanel} /></div>`
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
