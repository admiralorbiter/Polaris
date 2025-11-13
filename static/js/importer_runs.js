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
      profileAlert: document.getElementById("survivorship-profile-alert"),
      profileLabel: document.querySelector("[data-profile-label]"),
      profileDescription: document.querySelector("[data-profile-description]"),
      profileGroups: document.querySelector(".survivorship-profile-groups"),
      profileManageButton: document.getElementById("survivorship-profile-manage"),
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
      dedupeSummary: {
        totalRows: 0,
        runsWithAuto: 0,
        topRunId: null,
        topRunCount: 0,
      },
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

    function renderDedupeBadge(count, runId, status, badgeClass, label) {
      if (!count || count === 0) {
        return "";
      }
      const reviewUrl = `${config.api.adminBase}/dedupe/review?run_id=${runId}&status=${status}`;
      return `<a href="${reviewUrl}" class="badge bg-${badgeClass} text-decoration-none me-1" title="View ${label} candidates for this run">${count} ${label}</a>`;
    }

    function summarizeDedupe(runs) {
      return runs.reduce(
        (acc, run) => {
          const value = Number(run.rows_deduped_auto || 0);
          if (value > 0) {
            acc.totalRows += value;
            acc.runsWithAuto += 1;
            if (value > acc.topRunCount) {
              acc.topRunCount = value;
              acc.topRunId = run.id;
            }
          }
          return acc;
        },
        {
          totalRows: 0,
          runsWithAuto: 0,
          topRunId: null,
          topRunCount: 0,
        },
      );
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
        row.innerHTML = `<td colspan="10" class="text-center py-5 text-muted">No runs matched your filters.</td>`;
        elements.tableBody.appendChild(row);
        return;
      }

      runs.forEach((run) => {
        const row = document.createElement("tr");
        row.dataset.runId = String(run.id);
        const dryRunBadge = run.dry_run ? '<span class="badge bg-warning text-dark ms-2">DRY RUN</span>' : "";
        const dedupeAutoBadge = renderDedupeBadge(run.rows_dedupe_auto ?? 0, run.id, "auto_merged", "success", "Auto-merged");
        const dedupeReviewBadge = renderDedupeBadge(run.rows_dedupe_manual_review ?? 0, run.id, "pending", "warning", "Needs Review");
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
            <div class="small text-info">
              ${run.rows_deduped_auto ?? 0} auto-resolved duplicates
            </div>
            <div class="small text-muted">
              ${run.rows_skipped_duplicates} dupes · ${run.rows_missing_external_id} missing IDs
            </div>
          </td>
          <td>
            <div class="small">
              ${dedupeAutoBadge}${dedupeReviewBadge}
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

    function renderSummaryCards(stats, dedupeSummary = state.dedupeSummary) {
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

      const dedupeCard = document.createElement("div");
      dedupeCard.className = "col-sm-6 col-lg-3";
      const hasAuto = dedupeSummary.totalRows > 0;
      const topRunLabel = hasAuto
        ? `Top run ${dedupeSummary.topRunId} resolved ${dedupeSummary.topRunCount} duplicate${dedupeSummary.topRunCount === 1 ? "" : "s"}`
        : "No deterministic merges yet";
      dedupeCard.innerHTML = `
        <div class="card shadow-sm h-100 border-info">
          <div class="card-body">
            <h3 class="card-title h6 text-muted mb-2">Auto-resolved duplicates</h3>
            <p class="mb-1">
              <span class="display-6 text-info fw-semibold">${dedupeSummary.totalRows}</span> rows
            </p>
            <p class="mb-0 small text-muted">
              ${dedupeSummary.runsWithAuto} run${dedupeSummary.runsWithAuto === 1 ? "" : "s"} with deterministic merges.<br>
              ${topRunLabel}
            </p>
          </div>
        </div>
      `;

      elements.summaryCards.appendChild(totalCard);
      elements.summaryCards.appendChild(healthCard);
      elements.summaryCards.appendChild(sourceCard);
      elements.summaryCards.appendChild(dryRunCard);
      elements.summaryCards.appendChild(dedupeCard);
    }

    function updateLastUpdated() {
      if (!elements.lastUpdated) return;
      const now = new Date();
      elements.lastUpdated.textContent = `Last updated ${now.toLocaleTimeString()}`;
    }

    function loadStats(params) {
      fetchJSON(config.api.stats, params)
        .then((stats) => renderSummaryCards(stats, state.dedupeSummary))
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
            state.dedupeSummary = summarizeDedupe(data.runs || []);
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

    function renderSurvivorshipSummary(data) {
      if (!elements.modalContent) return;
      const container = elements.modalContent.querySelector('[data-field="survivorship"]');
      if (!container) return;
      container.innerHTML = "";

      const stats = (data && typeof data === "object" && data.stats) || {};
      const groups = (data && typeof data === "object" && data.groups) || {};
      const hasStats = Object.keys(stats).length > 0;
      const hasGroups = Object.keys(groups).length > 0;

      if (!hasStats && !hasGroups) {
        container.innerHTML = "<em>No survivorship decisions recorded for this run.</em>";
        return;
      }

      if (hasStats) {
        const badges = document.createElement("div");
        badges.className = "mb-2";
        const badgeConfig = [
          { key: "fields_changed", label: "Fields changed", variant: "primary" },
          { key: "fields_unchanged", label: "Unchanged", variant: "secondary" },
          { key: "manual_wins", label: "Manual wins", variant: "success" },
          { key: "incoming_overrides", label: "Incoming overrides", variant: "warning" },
          { key: "core_wins", label: "Core wins", variant: "info" },
        ];
        badgeConfig.forEach(({ key, label, variant }) => {
          const value = Number(stats[key] ?? 0);
          if (value <= 0) return;
          const badge = document.createElement("span");
          badge.className = `badge bg-${variant} me-2 mb-1`;
          badge.textContent = `${label}: ${value}`;
          badges.appendChild(badge);
        });
        if (badges.children.length > 0) {
          container.appendChild(badges);
        }
      }

      if (hasGroups) {
        const table = document.createElement("table");
        table.className = "table table-sm table-striped mb-0";
        table.innerHTML = `
          <thead>
            <tr>
              <th scope="col">Group</th>
              <th scope="col">Fields</th>
              <th scope="col">Changed</th>
              <th scope="col">Manual wins</th>
              <th scope="col">Incoming wins</th>
            </tr>
          </thead>
        `;

        const tbody = document.createElement("tbody");
        Object.entries(groups).forEach(([groupName, values]) => {
          const total = Number(values.total ?? 0);
          const changed = Number(values.changed ?? 0);
          const manualWins = Number(values.manual_wins ?? 0);
          const incomingWins = Number(values.incoming_wins ?? 0);
          const row = document.createElement("tr");
          row.innerHTML = `
            <th scope="row">${groupName.replace(/_/g, " ")}</th>
            <td>${total}</td>
            <td>${changed}</td>
            <td>${manualWins}</td>
            <td>${incomingWins}</td>
          `;
          tbody.appendChild(row);
        });
        table.appendChild(tbody);
        container.appendChild(table);
      }

      if (!container.textContent.trim() && container.children.length === 0) {
        container.innerHTML = "<em>No survivorship decisions recorded for this run.</em>";
      }
    }

    function renderSkipSummary(skipSummary, runId) {
      const summaryEl = document.getElementById("run-detail-skips-summary");
      const tableWrapper = document.getElementById("run-detail-skips-table-wrapper");
      const tableBody = document.getElementById("run-detail-skips-table-body");
      const paginationInfo = document.getElementById("run-detail-skips-pagination-info");
      const pagination = document.getElementById("run-detail-skips-pagination");
      const filterSelect = document.getElementById("skip-type-filter");

      if (!summaryEl || !tableWrapper || !tableBody) return;

      const total = skipSummary.total_skips || 0;
      const byType = skipSummary.by_type || {};
      const byReason = skipSummary.by_reason || {};

      if (total === 0) {
        summaryEl.innerHTML = '<span class="text-muted">No skipped records</span>';
        tableWrapper.classList.add("d-none");
        return;
      }

      // Render summary badges
      let summaryHtml = `<div class="mb-2"><strong>Total skipped: ${total}</strong></div>`;
      if (Object.keys(byType).length > 0) {
        summaryHtml += '<div class="mb-2">';
        Object.entries(byType).forEach(([type, count]) => {
          const badgeClass = type.includes("duplicate") ? "warning" : type.includes("missing") ? "danger" : "secondary";
          summaryHtml += `<span class="badge bg-${badgeClass} me-2 mb-1">${type.replace(/_/g, " ")}: ${count}</span>`;
        });
        summaryHtml += '</div>';
      }
      summaryEl.innerHTML = summaryHtml;
      tableWrapper.classList.remove("d-none");

      // Load and render skip records
      let currentPage = 1;
      const pageSize = 20;
      let currentFilter = "";

      function loadSkips(page = 1, skipType = "") {
        const params = new URLSearchParams({
          run_id: runId,
          limit: pageSize,
          offset: (page - 1) * pageSize,
        });
        if (skipType) {
          params.append("skip_type", skipType);
        }

        const skipListUrl = config.api.detailTemplate.replace("/runs/0", `/runs/${runId}/skips`);
        fetch(`${skipListUrl}?${params}`)
          .then((response) => response.json())
          .then((data) => {
            const items = data.items || [];
            const total = data.total || 0;

            if (items.length === 0) {
              tableBody.innerHTML = '<tr><td colspan="6" class="text-center text-muted py-3">No skipped records match the filter</td></tr>';
              paginationInfo.textContent = "";
              pagination.innerHTML = "";
              return;
            }

            tableBody.innerHTML = items
              .map((skip) => {
                const skipTypeBadge = skip.skip_type
                  .split("_")
                  .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
                  .join(" ");
                const badgeClass =
                  skip.skip_type === "duplicate_email" || skip.skip_type === "duplicate_name"
                    ? "warning"
                    : skip.skip_type === "duplicate_fuzzy"
                    ? "info"
                    : "secondary";
                const createdDate = skip.created_at ? new Date(skip.created_at).toLocaleString() : "—";
                const reasonPreview = skip.skip_reason ? (skip.skip_reason.length > 60 ? skip.skip_reason.substring(0, 60) + "..." : skip.skip_reason) : "—";
                return `
                  <tr>
                    <td>${skip.id}</td>
                    <td><span class="badge bg-${badgeClass}">${skipTypeBadge}</span></td>
                    <td title="${skip.skip_reason || ""}">${escapeHtml(reasonPreview)}</td>
                    <td>${escapeHtml(skip.record_key || "—")}</td>
                    <td>${createdDate}</td>
                    <td>
                      <button type="button" class="btn btn-sm btn-outline-primary skip-detail-btn" data-skip-id="${skip.id}">
                        View
                      </button>
                    </td>
                  </tr>
                `;
              })
              .join("");

            // Pagination
            const totalPages = Math.ceil(total / pageSize);
            paginationInfo.textContent = `Showing ${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, total)} of ${total}`;

            if (totalPages > 1) {
              let paginationHtml = '<ul class="pagination pagination-sm mb-0">';
              if (page > 1) {
                paginationHtml += `<li class="page-item"><a class="page-link" href="#" data-page="${page - 1}">Previous</a></li>`;
              }
              for (let i = Math.max(1, page - 2); i <= Math.min(totalPages, page + 2); i++) {
                paginationHtml += `<li class="page-item ${i === page ? "active" : ""}"><a class="page-link" href="#" data-page="${i}">${i}</a></li>`;
              }
              if (page < totalPages) {
                paginationHtml += `<li class="page-item"><a class="page-link" href="#" data-page="${page + 1}">Next</a></li>`;
              }
              paginationHtml += "</ul>";
              pagination.innerHTML = paginationHtml;

              pagination.querySelectorAll("a").forEach((link) => {
                link.addEventListener("click", (e) => {
                  e.preventDefault();
                  loadSkips(parseInt(link.dataset.page), currentFilter);
                });
              });
            } else {
              pagination.innerHTML = "";
            }

            // Add detail button handlers
            tableBody.querySelectorAll(".skip-detail-btn").forEach((btn) => {
              btn.addEventListener("click", () => {
                const skipId = btn.dataset.skipId;
                const skipDetailUrl = (config.api.base || "/api/importer") + `/skips/${skipId}`;
                fetch(skipDetailUrl)
                  .then((response) => response.json())
                  .then((skip) => {
                    showSkipDetailModal(skip);
                  })
                  .catch((error) => {
                    console.error("Failed to load skip detail:", error);
                    alert("Failed to load skip details");
                  });
              });
            });
          })
          .catch((error) => {
            console.error("Failed to load skips:", error);
            tableBody.innerHTML = '<tr><td colspan="6" class="text-center text-danger py-3">Failed to load skipped records</td></tr>';
          });
      }

      // Filter change handler
      if (filterSelect) {
        filterSelect.addEventListener("change", (e) => {
          currentFilter = e.target.value;
          currentPage = 1;
          loadSkips(1, currentFilter);
        });
      }

      // Initial load
      loadSkips(1, currentFilter);
    }

    function showSkipDetailModal(skip) {
      const modal = document.createElement("div");
      modal.className = "modal fade";
      modal.innerHTML = `
        <div class="modal-dialog modal-lg">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title">Skip Record #${skip.id}</h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
              <dl class="row">
                <dt class="col-sm-3">Skip Type</dt>
                <dd class="col-sm-9"><span class="badge bg-secondary">${skip.skip_type}</span></dd>
                <dt class="col-sm-3">Reason</dt>
                <dd class="col-sm-9">${escapeHtml(skip.skip_reason || "—")}</dd>
                <dt class="col-sm-3">Record Key</dt>
                <dd class="col-sm-9">${escapeHtml(skip.record_key || "—")}</dd>
                <dt class="col-sm-3">Created</dt>
                <dd class="col-sm-9">${skip.created_at ? new Date(skip.created_at).toLocaleString() : "—"}</dd>
                <dt class="col-sm-3">Details</dt>
                <dd class="col-sm-9">
                  <pre class="bg-light border rounded p-3 small mb-0">${JSON.stringify(skip.details_json || {}, null, 2)}</pre>
                </dd>
              </dl>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
            </div>
          </div>
        </div>
      `;
      document.body.appendChild(modal);
      const bsModal = new bootstrap.Modal(modal);
      bsModal.show();
      modal.addEventListener("hidden.bs.modal", () => {
        document.body.removeChild(modal);
      });
    }

    function escapeHtml(text) {
      if (!text) return "";
      const div = document.createElement("div");
      div.textContent = text;
      return div.innerHTML;
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
      const dedupeField = elements.modalContent.querySelector('[data-field="rows_deduped_auto"]');
      if (dedupeField) {
        const value = Number(detail.rows_deduped_auto ?? detail.counts_json?.core?.volunteers?.rows_deduped_auto ?? 0);
        dedupeField.textContent =
          value > 0
            ? `${value} row${value === 1 ? "" : "s"} auto-resolved`
            : "No deterministic duplicates resolved";
      }

      const dedupeAutoField = elements.modalContent.querySelector('[data-field="rows_dedupe_auto"]');
      if (dedupeAutoField) {
        const autoValue = Number(detail.rows_dedupe_auto ?? 0);
        const reviewValue = Number(detail.rows_dedupe_manual_review ?? 0);
        if (autoValue > 0 || reviewValue > 0) {
          const reviewUrl = `${config.api.adminBase}/dedupe/review?run_id=${detail.run_id}`;
          dedupeAutoField.innerHTML = `
            <div class="mb-2">
              <a href="${reviewUrl}&status=auto_merged" class="badge bg-success text-decoration-none me-2">
                ${autoValue} Auto-merged
              </a>
              <a href="${reviewUrl}&status=pending" class="badge bg-warning text-decoration-none">
                ${reviewValue} Needs Review
              </a>
            </div>
          `;
        } else {
          dedupeAutoField.textContent = "No dedupe candidates";
        }
      }

      renderSurvivorshipSummary(detail.survivorship);
      
      // Render skip summary and table
      if (detail.skip_summary) {
        renderSkipSummary(detail.skip_summary, detail.run_id);
      } else {
        const skipSummaryEl = document.getElementById("run-detail-skips-summary");
        if (skipSummaryEl) {
          skipSummaryEl.textContent = "No skipped records";
        }
      }
      
      // Render field statistics if available
      if (detail.field_stats) {
        renderFieldStatistics(detail.field_stats, detail.run_id);
      }

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

    function initializeProfileBanner() {
      if (!config.survivorshipProfile || !elements.profileLabel) return;
      const profile = config.survivorshipProfile;
      elements.profileLabel.textContent = profile.label || "Default survivorship";
      if (elements.profileDescription) {
        elements.profileDescription.textContent = profile.description || "";
      }
      if (elements.profileGroups) {
        elements.profileGroups.innerHTML = "";
        const groups = Array.isArray(profile.field_groups) ? profile.field_groups : [];
        if (groups.length > 0) {
          const list = document.createElement("ul");
          list.className = "mb-0 ps-3";
          groups.forEach((group) => {
            const item = document.createElement("li");
            const displayName = group.display_name || group.name || "Group";
            const fields = Array.isArray(group.fields) ? group.fields.join(", ") : "";
            item.innerHTML = fields ? `<span class="fw-semibold">${displayName}</span> — ${fields}` : `<span class="fw-semibold">${displayName}</span>`;
            list.appendChild(item);
          });
          elements.profileGroups.appendChild(list);
        }
      }
      if (elements.profileAlert) {
        elements.profileAlert.classList.remove("d-none");
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

      if (elements.profileManageButton) {
        elements.profileManageButton.addEventListener("click", (event) => {
          event.preventDefault();
          showToast("Profile management will be available in a future release.", "info");
        });
      }
    }

    initializeProfileBanner();
    attachEventListeners();
    updateAutoRefreshButton();
    setupAutoRefresh();
    loadRuns();
  });

  function getStatusBadge(rate) {
    if (rate >= 0.8) {
      return '<span class="badge bg-success">Good</span>';
    } else if (rate >= 0.5) {
      return '<span class="badge bg-warning text-dark">Warning</span>';
    } else {
      return '<span class="badge bg-danger">Critical</span>';
    }
  }

  function formatPercentage(rate) {
    return (rate * 100).toFixed(1) + "%";
  }

  function renderFieldStatistics(fieldStats, runId) {
    const section = document.getElementById("field-stats-section");
    if (!section) return;

    if (!fieldStats || (!fieldStats.source_fields && !fieldStats.target_fields && !fieldStats.unmapped_source_fields)) {
      section.classList.add("d-none");
      return;
    }

    section.classList.remove("d-none");

    // Render source fields
    renderSourceFields(fieldStats.source_fields || {});
    
    // Render target fields
    renderTargetFields(fieldStats.target_fields || {});
    
    // Render unmapped fields
    renderUnmappedFields(fieldStats.unmapped_source_fields || {});

    // Setup search and export handlers
    setupFieldStatsHandlers(runId);
  }

  function renderSourceFields(sourceFields) {
    const tbody = document.querySelector("#source-fields-table tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    const fields = Object.entries(sourceFields).sort((a, b) => a[0].localeCompare(b[0]));
    
    fields.forEach(([fieldName, stats]) => {
      const row = document.createElement("tr");
      const populationRate = stats.population_rate || 0;
      const hasTransform = stats.records_transformed > 0;
      
      row.innerHTML = `
        <td><code>${escapeHtml(fieldName)}</code></td>
        <td>${stats.target ? `<code>${escapeHtml(stats.target)}</code>` : "—"}</td>
        <td>${stats.records_with_value?.toLocaleString() || 0}</td>
        <td>${stats.total_records_processed?.toLocaleString() || 0}</td>
        <td>
          <div class="progress" style="height: 20px;">
            <div class="progress-bar ${populationRate >= 0.8 ? 'bg-success' : populationRate >= 0.5 ? 'bg-warning' : 'bg-danger'}" 
                 role="progressbar" style="width: ${formatPercentage(populationRate)}">
              ${formatPercentage(populationRate)}
            </div>
          </div>
        </td>
        <td>${hasTransform ? '<span class="badge bg-info">Yes</span>' : "—"}</td>
        <td>${getStatusBadge(populationRate)}</td>
      `;
      tbody.appendChild(row);
    });
  }

  function renderTargetFields(targetFields) {
    const tbody = document.querySelector("#target-fields-table tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    const fields = Object.entries(targetFields).sort((a, b) => a[0].localeCompare(b[0]));
    
    fields.forEach(([fieldName, stats]) => {
      const row = document.createElement("tr");
      const completenessRate = stats.completeness_rate || 0;
      const sourceFieldsList = (stats.source_fields || []).map(f => `<code>${escapeHtml(f)}</code>`).join(", ");
      
      row.innerHTML = `
        <td><code>${escapeHtml(fieldName)}</code></td>
        <td>${sourceFieldsList || "—"}</td>
        <td>${stats.total_records_populated?.toLocaleString() || 0}</td>
        <td>${stats.total_records_processed?.toLocaleString() || 0}</td>
        <td>
          <div class="progress" style="height: 20px;">
            <div class="progress-bar ${completenessRate >= 0.8 ? 'bg-success' : completenessRate >= 0.5 ? 'bg-warning' : 'bg-danger'}" 
                 role="progressbar" style="width: ${formatPercentage(completenessRate)}">
              ${formatPercentage(completenessRate)}
            </div>
          </div>
        </td>
        <td>${getStatusBadge(completenessRate)}</td>
      `;
      tbody.appendChild(row);
    });
  }

  function renderUnmappedFields(unmappedFields) {
    const tbody = document.querySelector("#unmapped-fields-table tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    const fields = Object.entries(unmappedFields).sort((a, b) => a[0].localeCompare(b[0]));
    
    if (fields.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No unmapped fields</td></tr>';
      return;
    }
    
    fields.forEach(([fieldName, stats]) => {
      const row = document.createElement("tr");
      const totalProcessed = stats.total_records_processed || 0;
      const withValue = stats.records_with_value || 0;
      const populationRate = totalProcessed > 0 ? withValue / totalProcessed : 0;
      
      row.innerHTML = `
        <td><code>${escapeHtml(fieldName)}</code></td>
        <td>${withValue.toLocaleString()}</td>
        <td>${totalProcessed.toLocaleString()}</td>
        <td>
          <div class="progress" style="height: 20px;">
            <div class="progress-bar ${populationRate >= 0.8 ? 'bg-success' : populationRate >= 0.5 ? 'bg-warning' : 'bg-danger'}" 
                 role="progressbar" style="width: ${formatPercentage(populationRate)}">
              ${formatPercentage(populationRate)}
            </div>
          </div>
        </td>
        <td>${getStatusBadge(populationRate)}</td>
      `;
      tbody.appendChild(row);
    });
  }

  function setupFieldStatsHandlers(runId) {
    // Search functionality
    const searchInputs = {
      "source-fields-search": "#source-fields-table tbody tr",
      "target-fields-search": "#target-fields-table tbody tr",
      "unmapped-fields-search": "#unmapped-fields-table tbody tr",
    };

    Object.entries(searchInputs).forEach(([inputId, selector]) => {
      const input = document.getElementById(inputId);
      if (input) {
        input.addEventListener("input", (e) => {
          const searchTerm = e.target.value.toLowerCase();
          const rows = document.querySelectorAll(selector);
          rows.forEach((row) => {
            const text = row.textContent.toLowerCase();
            row.style.display = text.includes(searchTerm) ? "" : "none";
          });
        });
      }
    });

    // Export functionality
    const exportButtons = {
      "export-source-fields-btn": "#source-fields-table",
      "export-target-fields-btn": "#target-fields-table",
      "export-unmapped-fields-btn": "#unmapped-fields-table",
    };

    Object.entries(exportButtons).forEach(([buttonId, tableSelector]) => {
      const button = document.getElementById(buttonId);
      if (button) {
        button.addEventListener("click", () => {
          exportTableToCSV(tableSelector, `run-${runId}-${buttonId.replace("export-", "").replace("-btn", "")}.csv`);
        });
      }
    });
  }

  function exportTableToCSV(tableSelector, filename) {
    const table = document.querySelector(tableSelector);
    if (!table) return;

    const rows = Array.from(table.querySelectorAll("tr"));
    const csv = rows.map((row) => {
      const cells = Array.from(row.querySelectorAll("th, td"));
      return cells
        .map((cell) => {
          const text = cell.textContent.trim();
          // Escape quotes and wrap in quotes if contains comma or quote
          if (text.includes(",") || text.includes('"') || text.includes("\n")) {
            return `"${text.replace(/"/g, '""')}"`;
          }
          return text;
        })
        .join(",");
    }).join("\n");

    const blob = new Blob([csv], { type: "text/csv" });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    window.URL.revokeObjectURL(url);
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }
})();
