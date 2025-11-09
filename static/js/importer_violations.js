(function () {
  "use strict";

  const bootstrapModal = window.bootstrap ? window.bootstrap.Modal : null;
  const bootstrapToast = window.bootstrap ? window.bootstrap.Toast : null;

  document.addEventListener("DOMContentLoaded", () => {
    const config = window.IMPORTER_DQ_CONFIG;
    if (!config) {
      console.warn("IMPORTER_DQ_CONFIG missing; DQ inbox will not initialize.");
      return;
    }

    const elements = {
      filterForm: document.getElementById("dq-filter-form"),
      resetButton: document.getElementById("dq-reset-btn"),
      refreshButton: document.getElementById("dq-refresh-btn"),
      exportButton: document.getElementById("dq-export-btn"),
      tableBody: document.getElementById("dq-table-body"),
      table: document.getElementById("dq-table"),
      loadingOverlay: document.getElementById("dq-loading-overlay"),
      pagination: document.getElementById("dq-pagination"),
      paginationSummary: document.getElementById("dq-pagination-summary"),
      lastUpdated: document.getElementById("dq-last-updated"),
      summaryCards: document.getElementById("dq-summary-cards"),
      modalElement: document.getElementById("dq-detail-modal"),
      modalTitle: document.getElementById("dq-detail-title"),
      modalLoader: document.getElementById("dq-detail-loader"),
      modalContent: document.getElementById("dq-detail-content"),
      modalUpdated: document.getElementById("dq-detail-updated"),
    };

    const modalFields = elements.modalContent
      ? {
          id: elements.modalContent.querySelector('[data-field="id"]'),
          run_id: elements.modalContent.querySelector('[data-field="run_id"]'),
          rule_code: elements.modalContent.querySelector('[data-field="rule_code"]'),
          severity: elements.modalContent.querySelector('[data-field="severity"]'),
          status: elements.modalContent.querySelector('[data-field="status"]'),
          created_at: elements.modalContent.querySelector('[data-field="created_at"]'),
          preview: elements.modalContent.querySelector('[data-field="preview"]'),
          source: elements.modalContent.querySelector('[data-field="source"]'),
          remediation_hint: elements.modalContent.querySelector('[data-field="remediation_hint"]'),
          staging_payload: elements.modalContent.querySelector('[data-field="staging_payload"]'),
          normalized_payload: elements.modalContent.querySelector('[data-field="normalized_payload"]'),
          violation_details: elements.modalContent.querySelector('[data-field="violation_details"]'),
        }
      : {};

    const state = {
      page: 1,
      sort: "-created_at",
      isLoading: false,
      lastResponse: null,
      modalInstance: bootstrapModal && elements.modalElement ? bootstrapModal.getOrCreateInstance(elements.modalElement) : null,
    };

    function withLoading(callback) {
      if (state.isLoading) return;
      state.isLoading = true;
      if (elements.loadingOverlay) elements.loadingOverlay.classList.remove("d-none");
      Promise.resolve(callback()).finally(() => {
        state.isLoading = false;
        if (elements.loadingOverlay) elements.loadingOverlay.classList.add("d-none");
      });
    }

    function buildQueryParams() {
      const params = new URLSearchParams();
      params.set("page", String(state.page));
      params.set("sort", state.sort);

      if (!elements.filterForm) return params;
      const formData = new FormData(elements.filterForm);

      const ruleCode = (formData.get("rule_code") || "").toString().trim();
      const severity = (formData.get("severity") || "").toString().trim();
      const status = (formData.get("status") || "").toString().trim();
      const runId = (formData.get("run_id") || "").toString().trim();
      const createdFrom = (formData.get("created_from") || "").toString().trim();
      const createdTo = (formData.get("created_to") || "").toString().trim();
      const pageSize = (formData.get("page_size") || "25").toString().trim();

      if (ruleCode) params.set("rule_code", ruleCode);
      if (severity) params.set("severity", severity);
      if (status) params.set("status", status);
      if (runId) params.set("run_id", runId);
      if (createdFrom) params.set("created_from", createdFrom);
      if (createdTo) params.set("created_to", createdTo);
      if (pageSize) params.set("per_page", pageSize);
      return params;
    }

    function fetchJSON(url, params, options = {}) {
      const requestUrl = params ? `${url}?${params.toString()}` : url;
      return fetch(requestUrl, { credentials: "same-origin", headers: { Accept: "application/json" }, ...options }).then(async (response) => {
        if (!response.ok) {
          if (response.status === 401) {
            window.location.href = "/login";
            return Promise.reject(new Error("Authentication required."));
          }
          const data = await response.json().catch(() => ({}));
          const message = data && data.error ? data.error : `Request failed with status ${response.status}`;
          throw new Error(message);
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

    function capitalize(text) {
      if (!text) return "";
      return text.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
    }

    function badgeClass(severity) {
      switch (severity) {
        case "error":
          return "bg-danger";
        case "warning":
          return "bg-warning text-dark";
        case "info":
          return "bg-info";
        default:
          return "bg-secondary";
      }
    }

    function statusBadgeClass(status) {
      switch (status) {
        case "open":
          return "bg-warning text-dark";
        case "fixed":
          return "bg-success";
        case "suppressed":
          return "bg-secondary";
        default:
          return "bg-secondary";
      }
    }

    function renderViolationsTable(violations) {
      if (!elements.tableBody) return;
      elements.tableBody.innerHTML = "";
      if (!violations.length) {
        const row = document.createElement("tr");
        row.innerHTML = `<td colspan="8" class="text-center py-5 text-muted">No violations matched your filters.</td>`;
        elements.tableBody.appendChild(row);
        return;
      }

      violations.forEach((violation) => {
        const row = document.createElement("tr");
        row.dataset.violationId = String(violation.id);
        row.innerHTML = `
          <th scope="row"><button type="button" class="btn btn-link p-0 dq-detail-link" data-violation-id="${violation.id}">${violation.id}</button></th>
          <td>${violation.run_id}</td>
          <td><span class="badge bg-secondary">${violation.rule_code}</span></td>
          <td><span class="badge ${badgeClass(violation.severity)}">${violation.severity.toUpperCase()}</span></td>
          <td><span class="badge ${statusBadgeClass(violation.status)}">${violation.status.toUpperCase()}</span></td>
          <td>${formatDateTime(violation.created_at)}</td>
          <td>${violation.preview ? escapeHtml(violation.preview) : "—"}</td>
          <td class="text-end">
            <button type="button" class="btn btn-outline-primary btn-sm dq-detail-link" data-violation-id="${violation.id}">View</button>
          </td>
        `;
        elements.tableBody.appendChild(row);
      });
    }

    function renderPagination(meta) {
      if (!elements.pagination || !elements.paginationSummary) return;
      elements.pagination.innerHTML = "";
      elements.paginationSummary.textContent = "";
      if (!meta.total_pages || meta.total_pages <= 1) return;

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
            loadViolations();
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
      elements.paginationSummary.textContent = `Showing ${from}–${to} of ${meta.total} violations`;
    }

    function renderSummaryCards(stats) {
      if (!elements.summaryCards) return;
      elements.summaryCards.innerHTML = "";

      const totalCard = createSummaryCard("Violations in view", String(stats.total));
      const severityEntries = Object.entries(stats.by_severity || {}).sort((a, b) => b[1] - a[1]);
      const severityText = severityEntries.length
        ? severityEntries.map(([key, count]) => `<span class="d-block">${capitalize(key)}: <strong>${count}</strong></span>`).join("")
        : "—";
      const severityCard = createSummaryCard("By severity", severityText, true);

      const statusEntries = Object.entries(stats.by_status || {}).sort((a, b) => b[1] - a[1]);
      const statusText = statusEntries.length
        ? statusEntries.map(([key, count]) => `<span class="d-block">${capitalize(key)}: <strong>${count}</strong></span>`).join("")
        : "—";
      const statusCard = createSummaryCard("By status", statusText, true);

      const topRule = Object.entries(stats.by_rule_code || {}).sort((a, b) => b[1] - a[1])[0];
      const topRuleText = topRule ? `${topRule[0]} (${topRule[1]})` : "—";
      const ruleCard = createSummaryCard("Top rule", topRuleText);

      elements.summaryCards.appendChild(totalCard);
      elements.summaryCards.appendChild(severityCard);
      elements.summaryCards.appendChild(statusCard);
      elements.summaryCards.appendChild(ruleCard);
    }

    function createSummaryCard(title, body, preserveHtml = false) {
      const col = document.createElement("div");
      col.className = "col-sm-6 col-lg-3";
      const card = document.createElement("div");
      card.className = "card shadow-sm h-100";
      card.innerHTML = `
        <div class="card-body">
          <h3 class="card-title h6 text-muted mb-2">${title}</h3>
          <p class="mb-0">${body}</p>
        </div>
      `;
      if (preserveHtml) {
        card.querySelector("p").innerHTML = body;
      }
      col.appendChild(card);
      return col;
    }

    function updateLastUpdated() {
      if (!elements.lastUpdated) return;
      const now = new Date();
      elements.lastUpdated.textContent = `Last updated ${now.toLocaleTimeString()}`;
    }

    function loadStats(params) {
      fetchJSON(config.api.stats, params)
        .then((stats) => renderSummaryCards(stats))
        .catch((error) => console.error("Failed to load violation stats", error));
    }

    function loadRuleCodes() {
      if (!config.api.ruleCodes) return;
      fetchJSON(config.api.ruleCodes)
        .then((payload) => {
          const select = document.getElementById("filter-rule-code");
          if (!select || !payload.rule_codes) return;
          const existing = new Set(Array.from(select.options).map((opt) => opt.value));
          payload.rule_codes.forEach((code) => {
            if (!existing.has(code)) {
              const option = document.createElement("option");
              option.value = code;
              option.textContent = code;
              select.appendChild(option);
            }
          });
        })
        .catch((error) => console.error("Failed to load rule codes", error));
    }

    function loadViolations() {
      withLoading(() => {
        const params = buildQueryParams();
        return fetchJSON(config.api.list, params)
          .then((data) => {
            state.lastResponse = data;
            renderViolationsTable(data.violations || []);
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
            console.error("Failed to load violations", error);
            showToast(error.message);
          });
      });
    }

    function showToast(message, variant = "danger") {
      const existing = document.getElementById("dq-toast");
      if (existing) existing.remove();

      const toastContainer = document.createElement("div");
      toastContainer.id = "dq-toast";
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
      if (bootstrapToast) {
        const toast = bootstrapToast.getOrCreateInstance(toastContainer);
        toast.show();
        setTimeout(() => toastContainer.remove(), 8000);
      }
    }

    function openDetail(violationId) {
      if (!elements.modalElement || !elements.modalLoader || !elements.modalContent) return;
      elements.modalLoader.classList.remove("d-none");
      elements.modalContent.classList.add("d-none");
      if (state.modalInstance) state.modalInstance.show();

      fetchJSON(`${config.api.detailBase}${violationId}`)
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

    function updateModalFields(detail) {
      if (!elements.modalContent) return;
      if (elements.modalTitle) elements.modalTitle.textContent = `Violation ${detail.id}`;
      Object.entries(modalFields).forEach(([key, element]) => {
        if (!element) return;
        const value = detail[key] ?? "—";
        if (key === "staging_payload" || key === "normalized_payload" || key === "violation_details") {
          element.textContent = formatJson(value);
        } else if (key === "created_at") {
          element.textContent = formatDateTime(value);
        } else {
          element.textContent = value || "—";
        }
      });
      if (elements.modalUpdated) elements.modalUpdated.textContent = `Detail fetched ${new Date().toLocaleTimeString()}`;
    }

    function formatJson(value) {
      if (!value || Object.keys(value).length === 0) return "{}";
      try {
        return JSON.stringify(value, null, 2);
      } catch (err) {
        return String(value);
      }
    }

    function escapeHtml(value) {
      return value.replace(/[&<>"']/g, (char) => {
        const entities = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" };
        return entities[char] || char;
      });
    }

    function triggerExport() {
      const params = buildQueryParams();
      let downloadName = "dq_violations_export.csv";
      fetch(config.api.export + "?" + params.toString(), {
        credentials: "same-origin",
        headers: { Accept: "text/csv" },
      })
        .then(async (response) => {
          if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            const message = data && data.error ? data.error : `Export failed with status ${response.status}`;
            throw new Error(message);
          }
          const disposition = response.headers.get("Content-Disposition");
          if (disposition) {
            const filenameMatch = /filename="?([^"]+)"?/.exec(disposition);
            if (filenameMatch && filenameMatch[1]) {
              downloadName = filenameMatch[1];
            }
          }
          return response.blob();
        })
        .then((blob) => {
          const url = URL.createObjectURL(blob);
          const link = document.createElement("a");
          link.href = url;
          link.download = downloadName;
          document.body.appendChild(link);
          link.click();
          link.remove();
          URL.revokeObjectURL(url);
        })
        .catch((error) => showToast(error.message));
    }

    function attachEventListeners() {
      if (elements.filterForm) {
        elements.filterForm.addEventListener("submit", (event) => {
          event.preventDefault();
          state.page = 1;
          loadViolations();
        });
      }

      if (elements.resetButton) {
        elements.resetButton.addEventListener("click", (event) => {
          event.preventDefault();
          if (elements.filterForm) elements.filterForm.reset();
          state.page = 1;
          state.sort = "-created_at";
          loadViolations();
        });
      }

      if (elements.refreshButton) {
        elements.refreshButton.addEventListener("click", (event) => {
          event.preventDefault();
          loadViolations();
        });
      }

      if (elements.exportButton) {
        elements.exportButton.addEventListener("click", (event) => {
          event.preventDefault();
          triggerExport();
        });
      }

      if (elements.table) {
        elements.table.querySelectorAll("th[data-sort]").forEach((th) => {
          th.addEventListener("click", () => {
            const field = th.dataset.sort;
            if (!field) return;
            const currentSortField = state.sort.startsWith("-") ? state.sort.substring(1) : state.sort;
            const isDescending = state.sort.startsWith("-");
            if (currentSortField === field) {
              state.sort = isDescending ? field : `-${field}`;
            } else {
              state.sort = `-${field}`;
            }
            state.page = 1;
            loadViolations();
          });
        });
      }

      if (elements.tableBody) {
        elements.tableBody.addEventListener("click", (event) => {
          const target = event.target;
          if (!(target instanceof HTMLElement)) return;
          const violationId = Number(target.dataset.violationId || target.closest("[data-violation-id]")?.dataset.violationId);
          if (!violationId) return;
          if (target.classList.contains("dq-detail-link")) {
            event.preventDefault();
            openDetail(violationId);
          }
        });
      }
    }

    attachEventListeners();
    loadRuleCodes();
    loadViolations();
  });
})();

