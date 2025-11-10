(function () {
  "use strict";

  const bootstrapModal = window.bootstrap ? window.bootstrap.Modal : null;

  document.addEventListener("DOMContentLoaded", () => {
    const config = window.IMPORTER_RUNS_CONFIG;
    if (!config) {
      // eslint-disable-next-line no-console
      console.warn("IMPORTER_RUNS_CONFIG missing; runs dashboard will not initialize.");
      return;
    }

    const elements = {
      filterForm: document.getElementById("runs-filter-form"),
      resetButton: document.getElementById("runs-reset-btn"),
      refreshButton: document.getElementById("runs-refresh-btn"),
      refreshSpinner: document.getElementById("runs-refresh-spinner"),
      autoRefreshToggle: document.getElementById("runs-auto-refresh-toggle"),
      includeDryRuns: document.getElementById("filter-include-dry-runs"),
      pageSizeSelect: document.getElementById("filter-page-size"),
      tableBody: document.getElementById("runs-table-body"),
      table: document.getElementById("runs-table"),
      loadingOverlay: document.getElementById("runs-loading-overlay"),
      pagination: document.getElementById("runs-pagination"),
      paginationSummary: document.getElementById("runs-pagination-summary"),
      lastUpdated: document.getElementById("runs-last-updated"),
      summaryCards: document.getElementById("runs-summary-cards"),
      modalElement: document.getElementById("run-detail-modal"),
      modalTitle: document.getElementById("run-detail-title"),
      modalLoader: document.getElementById("run-detail-loader"),
      modalContent: document.getElementById("run-detail-content"),
      modalUpdated: document.getElementById("run-detail-updated"),
      modalDownload: document.getElementById("run-detail-download"),
      modalRetry: document.getElementById("run-detail-retry-btn"),
    };

    const state = {
      page: 1,
      sort: "-started_at",
      autoRefresh: (config.defaults && config.defaults.autoRefreshSeconds > 0) || false,
      autoRefreshTimer: null,
      filters: {},
      isLoading: false,
      lastResponse: null,
      modalInstance: bootstrapModal ? bootstrapModal.getOrCreateInstance(elements.modalElement) : null,
    };

    function withLoading(callback) {
      if (state.isLoading) {
        return;
      }
      state.isLoading = true;
      elements.loadingOverlay.classList.remove("d-none");
      elements.refreshSpinner.classList.remove("d-none");
      Promise.resolve(callback()).finally(() => {
        state.isLoading = false;
        elements.loadingOverlay.classList.add("d-none");
        elements.refreshSpinner.classList.add("d-none");
      });
    }

    function buildQuery() {
      const params = new URLSearchParams();
      params.set("page", String(state.page));
      params.set("sort", state.sort);

      const formData = new FormData(elements.filterForm);
      const search = (formData.get("search") || "").toString().trim();
      const source = (formData.get("source") || "").toString().trim();
      const status = (formData.get("status") || "").toString().trim();
      const startedFrom = (formData.get("started_from") || "").toString().trim();
      const startedTo = (formData.get("started_to") || "").toString().trim();
      const pageSize = formData.get("page_size") || config.defaults.pageSize;

      if (source) params.set("source", source);
      if (status) params.set("status", status);
      if (search) params.set("search", search);
      if (startedFrom) params.set("started_from", startedFrom);
      if (startedTo) params.set("started_to", startedTo);
      if (pageSize) params.set("per_page", pageSize);
      params.set("include_dry_runs", elements.includeDryRuns.checked ? "1" : "0");

      state.filters = {
        source,
        status,
        search,
        started_from: startedFrom,
        started_to: startedTo,
        include_dry_runs: elements.includeDryRuns.checked,
        page_size: Number(pageSize),
      };

      return params;
    }

    function fetchJSON(url, params, options = {}) {
      const requestUrl = params ? `${url}?${params.toString()}` : url;
      return fetch(requestUrl, {
        credentials: "same-origin",
        headers: { "Accept": "application/json" },
        ...options,
      }).then(async (response) => {
        if (!response.ok) {
          if (response.status === 401) {
            window.location.href = "/login";
            return Promise.reject(new Error("Authentication required."));
          }
          const data = await response.json().catch(() => ({}));
          const errorMessage = data && data.error ? data.error : `Request failed with status ${response.status}`;
          throw new Error(errorMessage);
        }
        return response.json();
      });
    }

    function formatDateTime(value) {
      if (!value) return "—";
      try {
        const date = new Date(value);
        return date.toLocaleString(undefined, {
          year: "numeric",
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        });
      } catch (err) {
        return value;
      }
    }

    function formatDuration(seconds) {
      if (seconds == null) return "—";
      const total = Math.max(0, Math.round(seconds));
      const minutes = Math.floor(total / 60);
      const remainingSeconds = total % 60;
      if (minutes === 0) {
        return `${remainingSeconds}s`;
      }
      if (minutes < 60) {
        return `${minutes}m ${remainingSeconds}s`;
      }
      const hours = Math.floor(minutes / 60);
      const remMinutes = minutes % 60;
      return `${hours}h ${remMinutes}m`;
    }

    function badgeForStatus(status) {
      const badgeMap = config.statusBadges || {};
      const variant = badgeMap[status] || "secondary";
      return `<span class="badge bg-${variant} text-uppercase">${status.replace(/_/g, " ")}</span>`;
    }

    function renderRunsTable(runs) {
      elements.tableBody.innerHTML = "";
      if (!runs.length) {
        const row = document.createElement("tr");
        row.innerHTML = `<td colspan="9" class="text-center py-5 text-muted">No runs matched your filters.</td>`;
        elements.tableBody.appendChild(row);
        return;
      }

      runs.forEach((run) => {
        const row = document.createElement("tr");
        row.dataset.runId = String(run.id);
        const dryRunBadge = run.dry_run ? '<span class="badge bg-warning text-dark ms-2">DRY RUN</span>' : "";
        row.innerHTML = `
          <th scope="row"><button type="button" class="btn btn-link p-0 run-detail-link" data-run-id="${run.id}">${run.id}</button></th>
          <td>${run.source || "—"} ${dryRunBadge}</td>
          <td>${badgeForStatus(run.status)}</td>
          <td>${formatDateTime(run.started_at)}</td>
          <td>${formatDateTime(run.finished_at)}</td>
          <td>
            <div class="small">
              <span class="fw-semibold">${run.rows_staged}</span> staged /
              <span class="text-success">${run.rows_validated}</span> validated /
              <span class="text-warning">${run.rows_quarantined}</span> quarantined
            </div>
          </td>
          <td>
            <div class="small">
              <span class="text-success">${run.rows_created}</span> created /
              <span class="text-primary">${run.rows_updated}</span> updated /
              <span class="text-muted">${run.rows_skipped_no_change}</span> no change
            </div>
            <div class="small text-muted">
              ${run.rows_skipped_duplicates} dupes · ${run.rows_missing_external_id} missing IDs
            </div>
          </td>
          <td>${formatDuration(run.duration_seconds)}</td>
          <td class="text-end">
            <div class="btn-group btn-group-sm" role="group">
              <button type="button" class="btn btn-outline-primary run-detail-link" data-run-id="${run.id}" title="View detail">
                View
              </button>
              <button type="button" class="btn btn-outline-secondary run-copy-json" data-run-id="${run.id}" title="Copy counts JSON">
                Copy JSON
              </button>
              <button type="button" class="btn btn-outline-success run-retry-btn ${run.can_retry ? "" : "disabled"}" data-run-id="${run.id}" ${run.can_retry ? "" : "disabled"} title="Retry run">
                Retry
              </button>
            </div>
          </td>
        `;
        elements.tableBody.appendChild(row);
      });
    }

    function renderPagination(meta) {
      elements.pagination.innerHTML = "";
      elements.paginationSummary.textContent = "";
      if (!meta.total_pages || meta.total_pages <= 1) {
        return;
      }

      const list = document.createElement("ul");
      list.className = "pagination pagination-sm mb-0 justify-content-end";

      function appendPage(page, label = null, disabled = false, active = false) {
        const li = document.createElement("li");
        li.className = `page-item ${disabled ? "disabled" : ""} ${active ? "active" : ""}`;
        const a = document.createElement("a");
        a.className = "page-link";
        a.href = "#";
        a.dataset.page = String(page);
        a.textContent = label || String(page);
        if (!disabled) {
          a.addEventListener("click", (event) => {
            event.preventDefault();
            if (page === state.page) return;
            state.page = page;
            loadRuns();
          });
        }
        li.appendChild(a);
        list.appendChild(li);
      }

      appendPage(Math.max(1, state.page - 1), "«", state.page === 1);
      for (let page = 1; page <= meta.total_pages; page += 1) {
        if (page === 1 || page === meta.total_pages || Math.abs(page - state.page) <= 2) {
          appendPage(page, null, false, page === state.page);
        } else if (Math.abs(page - state.page) === 3) {
          const ellipsis = document.createElement("li");
          ellipsis.className = "page-item disabled";
          ellipsis.innerHTML = `<span class="page-link">…</span>`;
          list.appendChild(ellipsis);
        }
      }
      appendPage(Math.min(meta.total_pages, state.page + 1), "»", state.page === meta.total_pages);
      elements.pagination.appendChild(list);

      const from = (meta.page - 1) * meta.page_size + 1;
      const to = Math.min(meta.page * meta.page_size, meta.total);
      elements.paginationSummary.textContent = `Showing ${from}–${to} of ${meta.total} runs`;
    }

    function renderSummaryCards(stats) {
      if (!elements.summaryCards) return;
      elements.summaryCards.innerHTML = "";

      const totalCard = document.createElement("div");
      totalCard.className = "col-sm-6 col-lg-3";
      totalCard.innerHTML = `
        <div class="card shadow-sm h-100">
          <div class="card-body">
            <h3 class="card-title h6 text-muted mb-2">Runs in view</h3>
            <p class="display-6 mb-0">${stats.total}</p>
          </div>
        </div>
      `;

      const succeeded = stats.by_status?.succeeded || 0;
      const failed = (stats.by_status?.failed || 0) + (stats.by_status?.partially_failed || 0);
      const running = stats.by_status?.running || 0;

      const healthCard = document.createElement("div");
      healthCard.className = "col-sm-6 col-lg-3";
      healthCard.innerHTML = `
        <div class="card shadow-sm h-100">
          <div class="card-body">
            <h3 class="card-title h6 text-muted mb-2">Run health</h3>
            <p class="mb-0">
              <span class="text-success fw-semibold">${succeeded}</span> succeeded<br>
              <span class="text-danger fw-semibold">${failed}</span> failed<br>
              <span class="text-info fw-semibold">${running}</span> running
            </p>
          </div>
        </div>
      `;

      const topSourceEntry = Object.entries(stats.by_source || {}).sort((a, b) => b[1] - a[1])[0];
      const topSource = topSourceEntry ? `${topSourceEntry[0]} (${topSourceEntry[1]})` : "—";
      const sourceCard = document.createElement("div");
      sourceCard.className = "col-sm-6 col-lg-3";
      sourceCard.innerHTML = `
        <div class="card shadow-sm h-100">
          <div class="card-body">
            <h3 class="card-title h6 text-muted mb-2">Top source</h3>
            <p class="mb-0">${topSource}</p>
          </div>
        </div>
      `;

      const dryRunData = stats.by_dry_run || {};
      const dryRunCount =
        dryRunData.true ?? dryRunData["true"] ?? dryRunData["1"] ?? dryRunData["True"] ?? 0;
      const standardCount =
        dryRunData.false ?? dryRunData["false"] ?? dryRunData["0"] ?? dryRunData["False"] ?? 0;
      const dryRunCard = document.createElement("div");
      dryRunCard.className = "col-sm-6 col-lg-3";
      dryRunCard.innerHTML = `
        <div class="card shadow-sm h-100">
          <div class="card-body">
            <h3 class="card-title h6 text-muted mb-2">Run type</h3>
            <p class="mb-0">
              <span class="badge bg-warning text-dark me-2">Dry runs</span>${dryRunCount}<br>
              <span class="badge bg-primary me-2">Standard</span>${standardCount}<br>
              <small class="text-muted">${state.autoRefresh ? `Auto refresh every ${config.defaults.autoRefreshSeconds}s` : "Auto refresh paused"}</small>
            </p>
          </div>
        </div>
      `;

      elements.summaryCards.appendChild(totalCard);
      elements.summaryCards.appendChild(healthCard);
      elements.summaryCards.appendChild(sourceCard);
      elements.summaryCards.appendChild(dryRunCard);
    }

    function updateLastUpdated() {
      if (!elements.lastUpdated) return;
      const now = new Date();
      elements.lastUpdated.textContent = `Last updated ${now.toLocaleTimeString()}`;
    }

    function loadStats(params) {
      fetchJSON(config.api.stats, params)
        .then((stats) => renderSummaryCards(stats))
        .catch((error) => {
          // eslint-disable-next-line no-console
          console.error("Failed to load run stats", error);
        });
    }

    function loadRuns() {
      withLoading(() => {
        const params = buildQuery();
        return fetchJSON(config.api.list, params)
          .then((data) => {
            state.lastResponse = data;
            renderRunsTable(data.runs || []);
            renderPagination({
              page: data.page,
              page_size: data.page_size,
              total: data.total,
              total_pages: data.total_pages,
            });
            updateLastUpdated();
            loadStats(params);
          })
          .catch((error) => {
            // eslint-disable-next-line no-console
            console.error("Failed to load runs", error);
            showToast(error.message);
          });
      });
    }

    function showToast(message, variant = "danger") {
      const existing = document.getElementById("runs-dashboard-toast");
      if (existing) existing.remove();

      const toastContainer = document.createElement("div");
      toastContainer.id = "runs-dashboard-toast";
      toastContainer.className = `toast align-items-center text-bg-${variant} border-0 position-fixed top-0 end-0 m-3`;
      toastContainer.setAttribute("role", "alert");
      toastContainer.setAttribute("aria-live", "assertive");
      toastContainer.setAttribute("aria-atomic", "true");
      toastContainer.innerHTML = `
        <div class="d-flex">
          <div class="toast-body">${message}</div>
          <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
      `;
      document.body.appendChild(toastContainer);
      const toast = bootstrap.Toast.getOrCreateInstance(toastContainer);
      toast.show();
      setTimeout(() => toastContainer.remove(), 8000);
    }

    function copyCountsJson(runId) {
      if (!state.lastResponse) return;
      const run = (state.lastResponse.runs || []).find((item) => item.id === runId);
      if (!run) {
        showToast("Unable to locate run counts for copy.", "warning");
        return;
      }
      const json = JSON.stringify(run.counts_digest || {}, null, 2);
      navigator.clipboard.writeText(json).then(
        () => showToast(`Counts copied for run ${runId}.`, "success"),
        () => showToast("Failed to copy counts JSON.", "warning"),
      );
    }

    function buildDetailUrl(runId) {
      const template = config.api.detailTemplate;
      if (!template) return "";
      if (template.includes("/0/")) {
        return template.replace("/0/", `/${runId}/`);
      }
      if (template.endsWith("/0")) {
        return template.replace(/\/0$/, `/${runId}`);
      }
      return template.replace(/0$/, String(runId));
    }

    function buildRetryUrl(runId) {
      return `${config.api.adminBase}/${runId}/retry`;
    }

    function buildDownloadUrl(runId) {
      return `${config.api.adminBase}/${runId}/download`;
    }

    function updateModalFields(detail) {
      if (!elements.modalContent) return;
      elements.modalTitle.textContent = `Run ${detail.run_id}`;
      elements.modalContent.querySelector('[data-field="run_id"]').textContent = detail.run_id;
      elements.modalContent.querySelector('[data-field="source"]').textContent = detail.source || "—";
      elements.modalContent.querySelector('[data-field="status_badge"]').innerHTML = badgeForStatus(detail.status);
      elements.modalContent.querySelector('[data-field="dry_run"]').textContent = detail.dry_run ? "Yes" : "No";
      elements.modalContent.querySelector('[data-field="duration"]').textContent = formatDuration(detail.duration_seconds);
      elements.modalContent.querySelector('[data-field="counts_json"]').textContent = JSON.stringify(detail.counts_json || {}, null, 2);
      elements.modalContent.querySelector('[data-field="metrics_json"]').textContent = JSON.stringify(detail.metrics_json || {}, null, 2);
      elements.modalContent.querySelector('[data-field="error_summary"]').textContent = detail.error_summary || "—";

      const triggered = detail.triggered_by;
      const triggeredField = elements.modalContent.querySelector('[data-field="triggered_by"]');
      if (triggered) {
        triggeredField.textContent = `${triggered.display_name || triggered.username} (${triggered.email})`;
      } else {
        triggeredField.textContent = "—";
      }

      elements.modalUpdated.textContent = `Detail fetched ${new Date().toLocaleTimeString()}`;
      const dryRunBanner = document.getElementById("run-detail-dry-run-banner");
      if (dryRunBanner) {
        dryRunBanner.classList.toggle("d-none", !detail.dry_run);
      }

      if (detail.download_available) {
        elements.modalDownload.classList.remove("d-none");
        elements.modalDownload.href = buildDownloadUrl(detail.run_id);
        elements.modalDownload.textContent = "Download original file";
      } else {
        elements.modalDownload.classList.add("d-none");
        elements.modalDownload.removeAttribute("href");
      }

      if (detail.retry_available) {
        elements.modalRetry.classList.remove("d-none");
        elements.modalRetry.dataset.runId = detail.run_id;
        elements.modalRetry.disabled = false;
      } else {
        elements.modalRetry.classList.add("d-none");
        delete elements.modalRetry.dataset.runId;
      }
    }

    function openDetail(runId) {
      if (!elements.modalElement) return;
      elements.modalLoader.classList.remove("d-none");
      elements.modalContent.classList.add("d-none");
      if (state.modalInstance) {
        state.modalInstance.show();
      }

      fetchJSON(buildDetailUrl(runId))
        .then((detail) => {
          elements.modalLoader.classList.add("d-none");
          elements.modalContent.classList.remove("d-none");
          updateModalFields(detail);
        })
        .catch((error) => {
          elements.modalLoader.classList.add("d-none");
          showToast(error.message);
        });
    }

    function triggerRetry(runId) {
      fetchJSON(buildRetryUrl(runId), null, { method: "POST" })
        .then(() => {
          showToast(`Retry queued for run ${runId}.`, "success");
          loadRuns();
        })
        .catch((error) => showToast(error.message));
    }

    function toggleAutoRefresh() {
      state.autoRefresh = !state.autoRefresh;
      updateAutoRefreshButton();
      setupAutoRefresh();
    }

    function updateAutoRefreshButton() {
      if (!elements.autoRefreshToggle) return;
      elements.autoRefreshToggle.textContent = state.autoRefresh ? "Auto Refresh (On)" : "Auto Refresh (Off)";
      elements.autoRefreshToggle.classList.toggle("btn-outline-success", state.autoRefresh);
      elements.autoRefreshToggle.classList.toggle("btn-outline-secondary", !state.autoRefresh);
    }

    function setupAutoRefresh() {
      if (state.autoRefreshTimer) {
        clearInterval(state.autoRefreshTimer);
        state.autoRefreshTimer = null;
      }
      if (!state.autoRefresh) return;
      const interval = Math.max(5, config.defaults.autoRefreshSeconds || 30) * 1000;
      state.autoRefreshTimer = setInterval(() => {
        if (!state.isLoading) {
          loadRuns();
        }
      }, interval);
    }

    function resetFilters() {
      elements.filterForm.reset();
      elements.includeDryRuns.checked = true;
      if (config.defaults && config.defaults.pageSize) {
        elements.pageSizeSelect.value = String(config.defaults.pageSize);
      }
      state.page = 1;
      state.sort = "-started_at";
      loadRuns();
    }

    function applySort(thElement) {
      const field = thElement.dataset.sort;
      if (!field) return;
      const currentSort = state.sort.startsWith("-") ? state.sort.substring(1) : state.sort;
      const isDescending = state.sort.startsWith("-");
      if (currentSort === field) {
        state.sort = isDescending ? field : `-${field}`;
      } else {
        state.sort = `-${field}`;
      }
      state.page = 1;
      loadRuns();
    }

    function attachEventListeners() {
      if (elements.filterForm) {
        elements.filterForm.addEventListener("submit", (event) => {
          event.preventDefault();
          state.page = 1;
          loadRuns();
        });
      }

      if (elements.resetButton) {
        elements.resetButton.addEventListener("click", (event) => {
          event.preventDefault();
          resetFilters();
        });
      }

      if (elements.refreshButton) {
        elements.refreshButton.addEventListener("click", (event) => {
          event.preventDefault();
          loadRuns();
        });
      }

      if (elements.autoRefreshToggle) {
        elements.autoRefreshToggle.addEventListener("click", (event) => {
          event.preventDefault();
          toggleAutoRefresh();
        });
      }

      if (elements.table) {
        elements.table.querySelectorAll("th[data-sort]").forEach((th) => {
          th.addEventListener("click", () => applySort(th));
        });
      }

      if (elements.tableBody) {
        elements.tableBody.addEventListener("click", (event) => {
          const target = event.target;
          if (!(target instanceof HTMLElement)) return;
          const runId = Number(target.dataset.runId || target.closest("[data-run-id]")?.dataset.runId);
          if (!runId) return;

          if (target.classList.contains("run-detail-link")) {
            event.preventDefault();
            openDetail(runId);
          } else if (target.classList.contains("run-copy-json")) {
            event.preventDefault();
            copyCountsJson(runId);
          } else if (target.classList.contains("run-retry-btn") && !target.classList.contains("disabled")) {
            event.preventDefault();
            triggerRetry(runId);
          }
        });
      }

      if (elements.modalRetry) {
        elements.modalRetry.addEventListener("click", (event) => {
          event.preventDefault();
          const runId = Number(elements.modalRetry.dataset.runId);
          if (runId) {
            elements.modalRetry.disabled = true;
            triggerRetry(runId);
          }
        });
      }
    }

    attachEventListeners();
    updateAutoRefreshButton();
    setupAutoRefresh();
    loadRuns();
  });
})();
