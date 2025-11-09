(function () {
  "use strict";

  const bootstrapModal = window.bootstrap ? window.bootstrap.Modal : null;
  const bootstrapToast = window.bootstrap ? window.bootstrap.Toast : null;
  const EMAIL_REGEX = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
  const PHONE_REGEX = /^\+[1-9]\d{7,14}$/;

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
      remediationStats: document.getElementById("dq-remediation-stats"),
      remediateModal: document.getElementById("dq-remediate-modal"),
      remediateForm: document.getElementById("dq-remediate-form"),
      remediatePayload: document.getElementById("dq-remediate-payload"),
      remediateNotes: document.getElementById("dq-remediate-notes"),
      remediateErrors: document.getElementById("dq-remediate-errors"),
      remediateSubmit: document.getElementById("dq-remediate-submit"),
      remediateTitle: document.getElementById("dq-remediate-title"),
      remediateUpdated: document.getElementById("dq-remediate-updated"),
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
      remediateModalInstance: bootstrapModal && elements.remediateModal ? bootstrapModal.getOrCreateInstance(elements.remediateModal) : null,
      detailCache: new Map(),
      activeRemediationId: null,
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
        const actions = [
          `<button type="button" class="btn btn-outline-primary dq-detail-link" data-violation-id="${violation.id}">View</button>`,
        ];
        if (violation.status === "open") {
          actions.push(
            `<button type="button" class="btn btn-primary dq-remediate-btn" data-violation-id="${violation.id}">Edit &amp; Requeue</button>`
          );
        }
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
            <div class="btn-group btn-group-sm" role="group">
              ${actions.join("")}
            </div>
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
            loadRemediationStats();
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

    function buildDetailUrl(violationId) {
      const template = config.api.detailTemplate;
      if (!template) return "";
      if (template.includes("/0/")) {
        return template.replace("/0/", `/${violationId}/`);
      }
      if (template.endsWith("/0")) {
        return `${template.slice(0, -2)}/${violationId}`;
      }
      return template.replace(/0$/, String(violationId));
    }

    function buildRemediateUrl(violationId) {
      const template = config.api.remediateTemplate;
      if (!template) return "";
      if (template.includes("/0/")) {
        return template.replace("/0/", `/${violationId}/`);
      }
      if (template.endsWith("/0")) {
        return `${template.slice(0, -2)}/${violationId}`;
      }
      return template.replace(/0$/, String(violationId));
    }

    function fetchViolationDetail(violationId) {
      if (state.detailCache.has(violationId)) {
        return Promise.resolve(state.detailCache.get(violationId));
      }
      const url = buildDetailUrl(violationId);
      return fetchJSON(url).then((detail) => {
        state.detailCache.set(violationId, detail);
        return detail;
      });
    }

    function openDetail(violationId) {
      if (!elements.modalElement || !elements.modalLoader || !elements.modalContent) return;
      elements.modalLoader.classList.remove("d-none");
      elements.modalContent.classList.add("d-none");
      if (state.modalInstance) state.modalInstance.show();

      fetchViolationDetail(violationId)
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
      state.detailCache.set(detail.id, detail);
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

    function stringifyJson(value) {
      try {
        return JSON.stringify(value ?? {}, null, 2);
      } catch (err) {
        return typeof value === "string" ? value : "{}";
      }
    }

    function clearRemediationErrors() {
      if (!elements.remediateErrors) return;
      elements.remediateErrors.classList.add("d-none");
      elements.remediateErrors.innerHTML = "";
    }

    function renderRemediationErrors(messages) {
      if (!elements.remediateErrors) return;
      const items = Array.isArray(messages) ? messages : [messages];
      const filtered = items.filter(Boolean);
      if (!filtered.length) {
        clearRemediationErrors();
        return;
      }
      elements.remediateErrors.innerHTML = `<ul class="mb-0">${filtered.map((msg) => `<li>${escapeHtml(String(msg))}</li>`).join("")}</ul>`;
      elements.remediateErrors.classList.remove("d-none");
    }

    function setRemediationLoading(isLoading) {
      if (!elements.remediateSubmit) return;
      elements.remediateSubmit.disabled = isLoading;
      elements.remediateSubmit.innerHTML = isLoading
        ? `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Submitting...`
        : `<i class="fas fa-sync-alt me-1"></i>Validate &amp; Requeue`;
    }

    function populateRemediationForm(detail) {
      if (!elements.remediateForm || !elements.remediatePayload) return;
      state.activeRemediationId = detail.id;
      elements.remediateForm.dataset.violationId = String(detail.id);
      if (elements.remediateTitle) elements.remediateTitle.textContent = `Remediate Violation ${detail.id}`;
      const preferredPayload =
        (detail.edited_payload && Object.keys(detail.edited_payload).length ? detail.edited_payload : null) ||
        detail.normalized_payload ||
        detail.staging_payload ||
        {};
      elements.remediatePayload.value = stringifyJson(preferredPayload);
      if (elements.remediateNotes) elements.remediateNotes.value = detail.remediation_notes || "";
      clearRemediationErrors();
      if (elements.remediateUpdated) {
        elements.remediateUpdated.textContent = `Draft generated ${new Date().toLocaleTimeString()}`;
      }
    }

    function validateRemediationPayload(payload) {
      const errors = [];
      if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
        errors.push("Payload must be a JSON object.");
        return errors;
      }
      const firstName = (payload.first_name || "").toString().trim();
      const lastName = (payload.last_name || "").toString().trim();
      const email = (payload.email || payload.email_normalized || "").toString().trim();
      const phone = (payload.phone_e164 || payload.phone || "").toString().trim();

      if (!firstName) errors.push("First name is required.");
      if (!lastName) errors.push("Last name is required.");
      if (!email && !phone) {
        errors.push("Provide at least one contact method (email or phone in E.164).");
      }
      if (email && !EMAIL_REGEX.test(email)) {
        errors.push("Email format appears invalid.");
      }
      if (phone && !PHONE_REGEX.test(phone)) {
        errors.push("Phone must be formatted in E.164 (e.g., +15551234567).");
      }
      return errors;
    }

    function openRemediationModal(violationId) {
      if (!elements.remediateModal || !state.remediateModalInstance) return;
      clearRemediationErrors();
      const detail = state.detailCache.get(violationId);
      const show = (violationDetail) => {
        populateRemediationForm(violationDetail);
        state.remediateModalInstance.show();
      };
      if (detail) {
        show(detail);
        return;
      }
      fetchViolationDetail(violationId)
        .then((violationDetail) => show(violationDetail))
        .catch((error) => {
          showToast(error.message);
        });
    }

    function postRemediation(violationId, payload, notes) {
      const url = buildRemediateUrl(violationId);
      return fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({ payload, notes }),
      }).then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          const error = new Error(data.error || "Remediation failed.");
          error.status = response.status;
          error.payload = data;
          throw error;
        }
        return data;
      });
    }

    function handleRemediationSubmit(event) {
      event.preventDefault();
      if (!elements.remediateForm || !elements.remediatePayload) return;
      const violationId = Number(elements.remediateForm.dataset.violationId);
      if (!violationId) {
        renderRemediationErrors("Missing violation identifier.");
        return;
      }
      let parsedPayload;
      try {
        parsedPayload = JSON.parse(elements.remediatePayload.value || "{}");
      } catch (err) {
        renderRemediationErrors("Payload is not valid JSON.");
        return;
      }
      const validationErrors = validateRemediationPayload(parsedPayload);
      if (validationErrors.length) {
        renderRemediationErrors(validationErrors);
        return;
      }
      setRemediationLoading(true);
      const notes = elements.remediateNotes ? elements.remediateNotes.value : "";
      postRemediation(violationId, parsedPayload, notes)
        .then((response) => {
          clearRemediationErrors();
          showToast("Row fixed and queued for import.", "success");
          if (state.remediateModalInstance) state.remediateModalInstance.hide();
          state.detailCache.delete(violationId);
          fetchViolationDetail(violationId).catch(() => {});
          loadViolations();
          loadRemediationStats();
        })
        .catch((error) => {
          if (error.status === 422 && error.payload && Array.isArray(error.payload.errors)) {
            const messages = error.payload.errors.map((item) => {
              if (!item) return null;
              const rule = item.rule_code ? `${item.rule_code}: ` : "";
              return `${rule}${item.message || "Validation failed."}`;
            });
            renderRemediationErrors(messages);
          } else if (error.payload && error.payload.error) {
            renderRemediationErrors(error.payload.error);
            showToast(error.payload.error);
          } else {
            const message = error.message || "Remediation failed.";
            renderRemediationErrors(message);
            showToast(message);
          }
        })
        .finally(() => {
          setRemediationLoading(false);
        });
    }

    function renderRemediationStats(stats) {
      if (!elements.remediationStats) return;
      elements.remediationStats.innerHTML = "";
      if (!stats || typeof stats.attempts !== "number") {
        const empty = document.createElement("div");
        empty.className = "col-12";
        empty.innerHTML = `<div class="card shadow-sm h-100"><div class="card-body"><p class="mb-0 text-muted">Remediation stats unavailable.</p></div></div>`;
        elements.remediationStats.appendChild(empty);
        return;
      }

      const attemptsText = `<strong>${stats.attempts}</strong> attempts`;
      const successesText = stats.successes
        ? `<span class="d-block">Successes: <strong>${stats.successes}</strong></span><span class="d-block">Failures: <strong>${stats.failures}</strong></span>`
        : "No successes yet.";
      const successRatePercent = Math.round((stats.success_rate || 0) * 1000) / 10;
      const successRateText = `${Number.isFinite(successRatePercent) ? successRatePercent.toFixed(1) : "0.0"}% success rate`;
      const fieldsText = (stats.top_fields || []).length
        ? stats.top_fields.map((item) => `<span class="d-block">${escapeHtml(item.field)}: <strong>${item.count}</strong></span>`).join("")
        : "—";
      const rulesText = (stats.top_rules || []).length
        ? stats.top_rules.map((item) => `<span class="d-block">${escapeHtml(item.rule_code)}: <strong>${item.count}</strong></span>`).join("")
        : "—";

      elements.remediationStats.appendChild(createSummaryCard(`Remediations (last ${stats.days} days)`, attemptsText, true));
      elements.remediationStats.appendChild(createSummaryCard("Success vs failure", successesText, true));
      elements.remediationStats.appendChild(createSummaryCard("Success rate", `<strong>${successRateText}</strong>`, true));
      elements.remediationStats.appendChild(createSummaryCard("Top fields edited", fieldsText, true));
      elements.remediationStats.appendChild(createSummaryCard("Rules encountered", rulesText, true));
    }

    function loadRemediationStats() {
      if (!elements.remediationStats || !config.api.remediationStats) return;
      const params = new URLSearchParams({ days: "30" });
      fetchJSON(config.api.remediationStats, params)
        .then((stats) => renderRemediationStats(stats))
        .catch((error) => console.error("Failed to load remediation stats", error));
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
          if (target.classList.contains("dq-remediate-btn")) {
            event.preventDefault();
            openRemediationModal(violationId);
            return;
          }
          if (target.classList.contains("dq-detail-link")) {
            event.preventDefault();
            openDetail(violationId);
          }
        });
      }

      if (elements.remediateForm) {
        elements.remediateForm.addEventListener("submit", handleRemediationSubmit);
      }

      if (elements.remediatePayload) {
        elements.remediatePayload.addEventListener("input", () => {
          clearRemediationErrors();
          if (elements.remediateUpdated) {
            elements.remediateUpdated.textContent = `Draft updated ${new Date().toLocaleTimeString()}`;
          }
        });
      }
    }

    attachEventListeners();
    loadRuleCodes();
    loadViolations();
  });
})();

