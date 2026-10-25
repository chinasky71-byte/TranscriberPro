(() => {
  "use strict";

  let source = null;
  let currentJob = "";

  function panel() {
    return document.getElementById("logs-panel");
  }

  function openLogs(jobId, name) {
    currentJob = jobId;
    document.getElementById("logs-title").textContent = name || jobId;
    const pre = document.getElementById("logs");
    pre.textContent = "";
    window.dispatchEvent(new CustomEvent("tp-logs-open"));

    if (source) {
      source.close();
      source = null;
    }
    source = new EventSource("/api/events?job_id=" + encodeURIComponent(jobId));

    source.onmessage = (event) => {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch (err) {
        return;
      }
      if (data.kind === "log" && data.line) {
        pre.textContent += data.line + "\n";
      } else if (data.kind === "status" && data.status) {
        pre.textContent += "[status] " + data.status + "\n";
      } else if (data.kind === "progress" && typeof data.percent === "number") {
        pre.textContent += "[progress] " + data.percent + "% " + (data.phase || "") + "\n";
      }
      if (pre.textContent.length > 200000) {
        pre.textContent = pre.textContent.slice(-150000);
      }
      pre.scrollTop = pre.scrollHeight;
    };
  }

  function closeLogs() {
    if (source) {
      source.close();
      source = null;
    }
    currentJob = "";
    window.dispatchEvent(new CustomEvent("tp-logs-close"));
  }

  document.addEventListener("click", (event) => {
    const logButton = event.target.closest(".js-log");
    if (logButton) {
      event.preventDefault();
      openLogs(logButton.dataset.job, logButton.dataset.name);
      return;
    }
    if (event.target && event.target.id === "logs-close") {
      event.preventDefault();
      closeLogs();
    }
  });

  window.addEventListener("beforeunload", () => {
    if (source) {
      source.close();
    }
  });
})();
