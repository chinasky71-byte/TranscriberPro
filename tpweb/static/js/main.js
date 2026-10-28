import { html, render, useState, useEffect } from '/static/js/lib.js';
import { loadTexts, t } from '/static/js/i18n.js';
import { connect, startPolling, refreshQueue, refreshJob, refreshHistoryCount, setState, useStore } from '/static/js/store.js';
import { TitleBar, TabBar } from '/static/js/chrome.js';
import { QueuePanel } from '/static/js/queue_panel.js';
import { CenterPanel, RightPanel } from '/static/js/side_panels.js';
import { HistoryView } from '/static/js/history_view.js';
import { SettingsDialog } from '/static/js/settings.js';
import { MessageHost } from '/static/js/dialogs.js';
import { GlossaryDialog } from '/static/js/tools_glossary.js';

function App() {
  const tab = useStore((s) => s.ui.tab);
  const settingsOpen = useStore((s) => !!s.ui.settings);
  const tool = useStore((s) => s.ui.tool);
  return html`<div class="window">
    <${TitleBar} />
    <${TabBar} />
    <main class="stack">
      ${tab === 'queue'
        ? html`<div class="splitter"><${QueuePanel} /><${CenterPanel} /><${RightPanel} /></div>`
        : html`<div class="history-wrap"><${HistoryView} onCount=${(n) => setState({ historyCount: n })} /></div>`}
    </main>
    ${settingsOpen ? html`<${SettingsDialog} />` : null}
    ${tool === 'glossary' ? html`<${GlossaryDialog} />` : null}
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
