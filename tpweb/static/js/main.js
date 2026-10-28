import { html, render, useState, useEffect } from '/static/js/lib.js';
import { loadTexts, t } from '/static/js/i18n.js';
import { connect, startPolling, refreshQueue, refreshJob, refreshHistoryCount, setState, useStore } from '/static/js/store.js';
import { TitleBar, TabBar } from '/static/js/chrome.js';
import { QueuePanel } from '/static/js/queue_panel.js';
import { CenterPanel, RightPanel } from '/static/js/side_panels.js';
import { HistoryView } from '/static/js/history_view.js';

function App() {
  const tab = useStore((s) => s.ui.tab);
  return html`<div class="window">
    <${TitleBar} />
    <${TabBar} />
    <main class="stack">
      ${tab === 'queue'
        ? html`<div class="splitter"><${QueuePanel} /><${CenterPanel} /><${RightPanel} /></div>`
        : html`<div class="history-wrap"><${HistoryView} onCount=${(n) => setState({ historyCount: n })} /></div>`}
    </main>
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
