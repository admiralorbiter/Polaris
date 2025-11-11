(() => {
  const csvForm = document.getElementById("importer-upload-form");
  const salesforceForm = document.getElementById("salesforce-import-form");

  if (!csvForm && !salesforceForm) {
    return;
  }

  const statusContainer = document.getElementById("importer-run-status");
  const csvFeedbackEl = document.getElementById("importer-upload-feedback");
  const salesforceFeedbackEl = document.getElementById("salesforce-import-feedback");
  const csvSubmitButton = csvForm?.querySelector("button[type='submit']") ?? null;
  const salesforceSubmitButton = salesforceForm?.querySelector("button[type='submit']") ?? null;
  const stopPollingButton = document.getElementById("salesforce-stop-polling");

  const statusTemplate =
    csvForm?.dataset.statusEndpoint ||
    salesforceForm?.dataset.statusEndpoint ||
    statusContainer?.dataset.statusEndpoint ||
    "";

  const terminalStatuses = new Set(["succeeded", "failed", "cancelled", "partially_failed"]);
  const MAX_POLL_DURATION_MS = 5 * 60 * 1000;

  let pollingTimeoutId = null;
  let pollingStartMs = 0;
  let pollingContext = null;
  let pollingPaused = false;

  function showFeedback(targetEl, message, level = "info") {
    if (!targetEl) {
      return;
    }
    targetEl.style.display = "block";
    targetEl.className = `alert alert-${level}`;
    targetEl.textContent = message;
  }

  function clearFeedback(targetEl) {
    if (!targetEl) {
      return;
    }
    targetEl.style.display = "none";
    targetEl.className = "";
    targetEl.textContent = "";
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

    const salesforceMetrics = payload.metrics?.salesforce || null;
    const salesforceCounts =
      (((payload.counts || {}).core || {}).volunteers || {}).salesforce || null;

    const salesforceMetricsItems = [];
    if (salesforceMetrics) {
      if (salesforceMetrics.batches_processed != null) {
        salesforceMetricsItems.push(
          `<li><strong>Batches processed:</strong> ${salesforceMetrics.batches_processed}</li>`
        );
      }
      if (salesforceMetrics.records_received != null) {
        salesforceMetricsItems.push(
          `<li><strong>Records received:</strong> ${salesforceMetrics.records_received}</li>`
        );
      }
      if (salesforceMetrics.records_staged != null) {
        salesforceMetricsItems.push(
          `<li><strong>Records staged:</strong> ${salesforceMetrics.records_staged}</li>`
        );
      }
      if (salesforceMetrics.max_source_updated_at) {
        salesforceMetricsItems.push(
          `<li><strong>Max source updated at:</strong> ${formatTimestamp(
            salesforceMetrics.max_source_updated_at
          )}</li>`
        );
      }
    }

    const salesforceCountItems = [];
    if (salesforceCounts) {
      salesforceCountItems.push(
        `<li><strong>Created:</strong> ${salesforceCounts.created ?? 0}</li>`
      );
      salesforceCountItems.push(
        `<li><strong>Updated:</strong> ${salesforceCounts.updated ?? 0}</li>`
      );
      salesforceCountItems.push(
        `<li><strong>Deleted:</strong> ${salesforceCounts.deleted ?? 0}</li>`
      );
      salesforceCountItems.push(
        `<li><strong>Unchanged:</strong> ${salesforceCounts.unchanged ?? 0}</li>`
      );
    }

    let salesforceExtras = "";
    if (salesforceMetricsItems.length || salesforceCountItems.length) {
      salesforceExtras += '<div class="mt-3">';
      salesforceExtras += '<h4 class="h6">Salesforce metrics</h4>';
      if (salesforceMetricsItems.length) {
        salesforceExtras += `<ul class="small mb-2 ps-3">${salesforceMetricsItems.join("")}</ul>`;
      }
      if (salesforceCountItems.length) {
        salesforceExtras +=
          '<h5 class="h6 text-muted">Core reconciliation</h5><ul class="small mb-2 ps-3">' +
          salesforceCountItems.join("") +
          "</ul>";
      }

      const unmappedFields = salesforceMetrics?.unmapped_fields || null;
      if (unmappedFields && Object.keys(unmappedFields).length) {
        const unmappedList = Object.entries(unmappedFields)
          .map(([field, count]) => `<li>${field}: ${count}</li>`)
          .join("");
        salesforceExtras +=
          '<div class="alert alert-warning mt-3 mb-0"><strong>Unmapped Salesforce fields detected:</strong><ul class="mb-0 ps-3">' +
          unmappedList +
          "</ul></div>";
      }

      const transformErrors = salesforceMetrics?.transform_errors || [];
      if (Array.isArray(transformErrors) && transformErrors.length) {
        const errorList = transformErrors.slice(0, 5).map((item) => `<li>${item}</li>`).join("");
        salesforceExtras +=
          '<div class="alert alert-danger mt-3 mb-0"><strong>Recent transform errors:</strong><ul class="mb-0 ps-3">' +
          errorList +
          "</ul></div>";
      }

      salesforceExtras += "</div>";
    }

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
          ${salesforceExtras}
        </div>
      </div>
    `;
  }

  function clearPollingTimeout() {
    if (pollingTimeoutId !== null) {
      clearTimeout(pollingTimeoutId);
      pollingTimeoutId = null;
    }
  }

  function stopPolling(options = {}) {
    const { reason, level = "info", preserveButton = false } = options;
    clearPollingTimeout();
    pollingPaused = false;

    if (stopPollingButton) {
      stopPollingButton.classList.add("d-none");
      stopPollingButton.dataset.runId = "";
    }

    if (pollingContext) {
      if (!preserveButton && pollingContext.submitButton) {
        pollingContext.submitButton.disabled = false;
      }
      if (reason && pollingContext.feedbackEl) {
        showFeedback(pollingContext.feedbackEl, reason, level);
      }
    }

    pollingContext = null;
  }

  function schedulePoll(runId, attempt = 0) {
    if (!pollingContext || pollingContext.runId !== runId) {
      return;
    }
    if (pollingPaused) {
      return;
    }

    const url = buildStatusUrl(runId);
    if (!url) {
      if (pollingContext.feedbackEl) {
        showFeedback(pollingContext.feedbackEl, "Unable to determine status endpoint for polling.", "danger");
      }
      stopPolling();
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
          if (pollingContext?.feedbackEl) {
            showFeedback(pollingContext.feedbackEl, `Run ${data.run_id} ${statusValue}.`, level);
          }
          stopPolling();
          return;
        }

        if (Date.now() - pollingStartMs > MAX_POLL_DURATION_MS) {
          stopPolling({
            reason: `Stopped polling run ${data.run_id} after 5 minutes. Check the runs dashboard for updates.`,
            level: "warning",
          });
          return;
        }

        if (document.hidden) {
          pollingPaused = true;
          return;
        }

        const delay = Math.min(10000, 2000 * Math.pow(1.5, attempt));
        clearPollingTimeout();
        pollingTimeoutId = window.setTimeout(() => schedulePoll(runId, attempt + 1), delay);
        pollingPaused = false;
      })
      .catch((error) => {
        console.error("Failed to poll import run status:", error);
        if (pollingContext?.feedbackEl) {
          showFeedback(pollingContext.feedbackEl, "Lost connection while polling run status. Retrying…", "warning");
        }
        if (document.hidden) {
          pollingPaused = true;
          return;
        }
        const delay = Math.min(10000, 2000 * Math.pow(1.5, attempt + 1));
        clearPollingTimeout();
        pollingTimeoutId = window.setTimeout(() => schedulePoll(runId, attempt + 1), delay);
        pollingPaused = false;
      });
  }

  function startPolling(runId, context = {}) {
    stopPolling({ preserveButton: true });

    pollingContext = {
      runId,
      feedbackEl: context.feedbackEl || null,
      submitButton: context.submitButton || null,
    };
    pollingStartMs = Date.now();
    pollingPaused = false;

    if (context.showStopButton && stopPollingButton) {
      stopPollingButton.classList.remove("d-none");
      stopPollingButton.dataset.runId = String(runId);
    } else if (stopPollingButton) {
      stopPollingButton.classList.add("d-none");
      stopPollingButton.dataset.runId = "";
    }

    schedulePoll(runId, 0);
  }

  if (stopPollingButton) {
    stopPollingButton.addEventListener("click", () => {
      if (!pollingContext) {
        stopPolling();
        return;
      }
      stopPolling({
        reason: `Stopped polling run ${pollingContext.runId}. Refresh the runs dashboard for updates.`,
      });
    });
  }

  if (typeof document !== "undefined") {
    document.addEventListener("visibilitychange", () => {
      if (!pollingContext) {
        return;
      }
      if (document.hidden) {
        pollingPaused = true;
        clearPollingTimeout();
      } else if (pollingPaused) {
        pollingPaused = false;
        schedulePoll(pollingContext.runId, 0);
      }
    });
  }

  if (csvForm) {
    csvForm.addEventListener("submit", (event) => {
      event.preventDefault();
      if (!csvForm.reportValidity()) {
        return;
      }

      const formData = new FormData(csvForm);
      if (csvSubmitButton) {
        csvSubmitButton.disabled = true;
      }
      showFeedback(csvFeedbackEl, "Uploading file and queueing run…", "info");

      fetch(csvForm.action, {
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
          csvForm.reset();
          showFeedback(
            csvFeedbackEl,
            `Run ${payload.run_id} queued on ${payload.queue || "imports"} (task ${payload.task_id}).`,
            "success"
          );
          startPolling(payload.run_id, {
            feedbackEl: csvFeedbackEl,
            submitButton: csvSubmitButton,
          });
        })
        .catch((error) => {
          console.error("Importer upload failed:", error);
          showFeedback(csvFeedbackEl, error.message || "Failed to start import run.", "danger");
          if (csvSubmitButton) {
            csvSubmitButton.disabled = false;
          }
        });
    });
  }

  if (salesforceForm) {
    salesforceForm.addEventListener("submit", (event) => {
      event.preventDefault();

      const formData = new FormData(salesforceForm);
      const wantsReset = formData.has("reset_watermark");
      if (wantsReset) {
        const confirmed = window.confirm(
          "Resetting the Salesforce watermark will force the next run to reprocess all eligible records. Continue?"
        );
        if (!confirmed) {
          return;
        }
      }

      const payload = {
        dry_run: formData.has("dry_run"),
        reset_watermark: wantsReset,
      };

      const recordLimitValue = formData.get("record_limit");
      if (recordLimitValue) {
        const parsedLimit = Number(recordLimitValue);
        if (!Number.isFinite(parsedLimit) || parsedLimit <= 0) {
          showFeedback(
            salesforceFeedbackEl,
            "Record limit must be a positive integer.",
            "danger"
          );
          return;
        }
        payload.record_limit = Math.floor(parsedLimit);
      }

      const notesValue = formData.get("notes");
      if (notesValue && typeof notesValue === "string") {
        const trimmed = notesValue.trim();
        if (trimmed) {
          payload.notes = trimmed;
        }
      }

      if (salesforceSubmitButton) {
        salesforceSubmitButton.disabled = true;
      }
      clearFeedback(salesforceFeedbackEl);
      showFeedback(salesforceFeedbackEl, "Queueing Salesforce import…", "info");

      fetch(salesforceForm.action, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify(payload),
      })
        .then(async (response) => {
          const data = await response.json().catch(() => ({}));
          if (!response.ok) {
            const message =
              data.error ||
              data.description ||
              `Failed to queue Salesforce run (status ${response.status}).`;
            throw new Error(message);
          }
          return data;
        })
        .then((data) => {
          salesforceForm.reset();
          showFeedback(
            salesforceFeedbackEl,
            `Run ${data.run_id} queued on ${data.queue || "imports"} (task ${data.task_id}).`,
            "success"
          );
          startPolling(data.run_id, {
            feedbackEl: salesforceFeedbackEl,
            submitButton: salesforceSubmitButton,
            showStopButton: true,
          });
        })
        .catch((error) => {
          console.error("Salesforce import trigger failed:", error);
          showFeedback(
            salesforceFeedbackEl,
            error.message || "Failed to queue Salesforce import.",
            "danger"
          );
          if (salesforceSubmitButton) {
            salesforceSubmitButton.disabled = false;
          }
        });
    });
  }

  document.querySelectorAll(".importer-retry-btn").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      const button = event.currentTarget;
      const endpoint = button.dataset.retryEndpoint;

      if (!endpoint) {
        showFeedback(csvFeedbackEl, "Retry endpoint not configured.", "danger");
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
              payload.error ||
              payload.description ||
              `Failed to retry run (status ${response.status}).`;
            throw new Error(message);
          }
          return payload;
        })
        .then((payload) => {
          showFeedback(
            csvFeedbackEl,
            `Run ${payload.run_id} retried and queued on ${payload.queue || "imports"} (task ${payload.task_id}).`,
            "success"
          );
          startPolling(payload.run_id, {
            feedbackEl: csvFeedbackEl,
            submitButton: csvSubmitButton,
          });
          setTimeout(() => {
            window.location.reload();
          }, 2000);
        })
        .catch((error) => {
          console.error("Importer retry failed:", error);
          showFeedback(csvFeedbackEl, error.message || "Failed to retry import run.", "danger");
          button.disabled = false;
          button.innerHTML = '<i class="fas fa-redo me-1"></i> Retry';
        });
    });
  });
})();

