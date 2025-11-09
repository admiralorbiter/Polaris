(() => {
  const form = document.getElementById("importer-upload-form");
  if (!form) {
    return;
  }

  const statusContainer = document.getElementById("importer-run-status");
  const feedbackEl = document.getElementById("importer-upload-feedback");
  const submitButton = form.querySelector("button[type='submit']");
  const statusTemplate =
    form.dataset.statusEndpoint || statusContainer?.dataset.statusEndpoint || "";
  const terminalStatuses = new Set(["succeeded", "failed", "cancelled", "partially_failed"]);

  function showFeedback(message, level = "info") {
    if (!feedbackEl) {
      return;
    }
    feedbackEl.style.display = "block";
    feedbackEl.className = `alert alert-${level}`;
    feedbackEl.textContent = message;
  }

  function buildStatusUrl(runId) {
    if (!statusTemplate) {
      return null;
    }
    if (statusTemplate.includes("/0/status")) {
      return statusTemplate.replace("/0/status", `/${runId}/status`);
    }
    return `${statusTemplate}/${runId}/status`;
  }

  function formatTimestamp(value) {
    if (!value) {
      return "—";
    }
    try {
      const date = new Date(value);
      return date.toLocaleString();
    } catch (err) {
      return value;
    }
  }

  function renderStatus(payload) {
    if (!statusContainer) {
      return;
    }
    const statusValue = (payload.status || "").toLowerCase();
    const badgeClass = (() => {
      if (statusValue === "succeeded") return "bg-success";
      if (statusValue === "running" || statusValue === "pending") return "bg-info";
      if (terminalStatuses.has(statusValue) && statusValue !== "succeeded") return "bg-danger";
      return "bg-secondary";
    })();

    statusContainer.innerHTML = `
      <div class="card shadow-sm">
        <div class="card-body">
          <div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
            <h3 class="h5 mb-0">Run ${payload.run_id}</h3>
            <span class="badge ${badgeClass} text-uppercase">${statusValue || "unknown"}</span>
          </div>
          <dl class="row mt-3 mb-0">
            <dt class="col-sm-3">Source</dt>
            <dd class="col-sm-9">${payload.source || "csv"}</dd>
            <dt class="col-sm-3">Dry run</dt>
            <dd class="col-sm-9">${payload.dry_run ? "Yes" : "No"}</dd>
            <dt class="col-sm-3">Started</dt>
            <dd class="col-sm-9">${formatTimestamp(payload.started_at)}</dd>
            <dt class="col-sm-3">Finished</dt>
            <dd class="col-sm-9">${formatTimestamp(payload.finished_at)}</dd>
          </dl>
          ${
            payload.error_summary
              ? `<div class="alert alert-danger mt-3 mb-0"><strong>Error:</strong> ${payload.error_summary}</div>`
              : ""
          }
          <details class="mt-3">
            <summary class="fw-semibold">Counts JSON</summary>
            <pre class="mt-2 bg-light p-2 rounded">${JSON.stringify(payload.counts || {}, null, 2)}</pre>
          </details>
        </div>
      </div>
    `;
  }

  function schedulePoll(runId, attempt = 0) {
    const url = buildStatusUrl(runId);
    if (!url) {
      showFeedback("Unable to determine status endpoint for polling.", "danger");
      return;
    }

    fetch(url, { headers: { Accept: "application/json" } })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Status request failed (${response.status})`);
        }
        return response.json();
      })
      .then((data) => {
        renderStatus(data);
        const statusValue = (data.status || "").toLowerCase();
        if (terminalStatuses.has(statusValue)) {
          const level = statusValue === "succeeded" ? "success" : "warning";
          showFeedback(`Run ${data.run_id} ${statusValue}.`, level);
          if (submitButton) {
            submitButton.disabled = false;
          }
          return;
        }

        const delay = Math.min(5000, 1000 * Math.pow(1.5, attempt));
        setTimeout(() => schedulePoll(runId, attempt + 1), delay);
      })
      .catch((error) => {
        console.error("Failed to poll import run status:", error);
        showFeedback("Lost connection while polling run status. Retrying…", "warning");
        const delay = Math.min(5000, 1000 * Math.pow(1.5, attempt + 1));
        setTimeout(() => schedulePoll(runId, attempt + 1), delay);
      });
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!form.reportValidity()) {
      return;
    }

    const formData = new FormData(form);
    if (submitButton) {
      submitButton.disabled = true;
    }
    showFeedback("Uploading file and queueing run…", "info");

    fetch(form.action, {
      method: "POST",
      body: formData,
      headers: { Accept: "application/json" },
    })
      .then(async (response) => {
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          const message =
            payload.description ||
            payload.error ||
            `Failed to queue run (status ${response.status}).`;
          throw new Error(message);
        }
        return payload;
      })
      .then((payload) => {
        form.reset();
        showFeedback(
          `Run ${payload.run_id} queued on ${payload.queue || "imports"} (task ${payload.task_id}).`,
          "success"
        );
        schedulePoll(payload.run_id);
      })
      .catch((error) => {
        console.error("Importer upload failed:", error);
        showFeedback(error.message || "Failed to start import run.", "danger");
        if (submitButton) {
          submitButton.disabled = false;
        }
      });
  });

  // Retry button handlers
  document.querySelectorAll(".importer-retry-btn").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      const button = event.currentTarget;
      const runId = button.dataset.runId;
      const endpoint = button.dataset.retryEndpoint;

      if (!endpoint) {
        showFeedback("Retry endpoint not configured.", "danger");
        return;
      }

      button.disabled = true;
      button.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i> Retrying...';

      fetch(endpoint, {
        method: "POST",
        headers: { Accept: "application/json" },
      })
        .then(async (response) => {
          const payload = await response.json().catch(() => ({}));
          if (!response.ok) {
            const message =
              payload.error || payload.description || `Failed to retry run (status ${response.status}).`;
            throw new Error(message);
          }
          return payload;
        })
        .then((payload) => {
          showFeedback(
            `Run ${payload.run_id} retried and queued on ${payload.queue || "imports"} (task ${payload.task_id}).`,
            "success"
          );
          // Start polling the retried run
          schedulePoll(payload.run_id);
          // Reload page after a short delay to refresh the table
          setTimeout(() => {
            window.location.reload();
          }, 2000);
        })
        .catch((error) => {
          console.error("Importer retry failed:", error);
          showFeedback(error.message || "Failed to retry import run.", "danger");
          button.disabled = false;
          button.innerHTML = '<i class="fas fa-redo me-1"></i> Retry';
        });
    });
  });
})();

