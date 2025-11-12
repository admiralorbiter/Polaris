(function () {
  "use strict";

  const bootstrapModal = window.bootstrap ? window.bootstrap.Modal : null;
  const bootstrapToast = window.bootstrap ? window.bootstrap.Toast : null;

  document.addEventListener("DOMContentLoaded", () => {
    const config = window.DEDUPE_REVIEW_CONFIG;
    if (!config) {
      console.warn("DEDUPE_REVIEW_CONFIG missing; dedupe review will not initialize.");
      return;
    }

    const elements = {
      filterForm: document.getElementById("review-filter-form"),
      refreshButton: document.getElementById("review-refresh-btn"),
      refreshSpinner: document.getElementById("review-refresh-spinner"),
      autoRefreshToggle: document.getElementById("review-auto-refresh-toggle"),
      candidatesList: document.getElementById("review-candidates-list"),
      loadingOverlay: document.getElementById("review-loading-overlay"),
      pagination: document.getElementById("review-pagination"),
      paginationSummary: document.getElementById("review-pagination-summary"),
      statsCards: {
        totalPending: document.getElementById("stat-total-pending"),
        reviewBand: document.getElementById("stat-review-band"),
        highConfidence: document.getElementById("stat-high-confidence"),
        agingOlder: document.getElementById("stat-aging-older"),
      },
      modalElement: document.getElementById("candidate-detail-modal"),
      modalTitle: document.getElementById("candidate-detail-title"),
      modalLoader: document.getElementById("candidate-detail-loader"),
      modalContent: document.getElementById("candidate-detail-content"),
      detailScoreBadge: document.getElementById("detail-score-badge"),
      detailMatchType: document.getElementById("detail-match-type"),
      detailTopFeatures: document.getElementById("detail-top-features"),
      detailPrimaryContact: document.getElementById("detail-primary-contact"),
      detailCandidateContact: document.getElementById("detail-candidate-contact"),
      detailSurvivorshipPreview: document.getElementById("detail-survivorship-preview"),
      actionForm: document.getElementById("candidate-action-form"),
      actionCandidateId: document.getElementById("action-candidate-id"),
      actionNotes: document.getElementById("action-notes"),
      actionErrors: document.getElementById("action-errors"),
      actionMergeBtn: document.getElementById("action-merge-btn"),
      actionRejectBtn: document.getElementById("action-reject-btn"),
      actionDeferBtn: document.getElementById("action-defer-btn"),
    };

    const state = {
      offset: 0,
      limit: 100,
      autoRefresh: false,
      autoRefreshTimer: null,
      isLoading: false,
      currentCandidateId: null,
      modalInstance: bootstrapModal && elements.modalElement ? bootstrapModal.getOrCreateInstance(elements.modalElement) : null,
    };

    function withLoading(callback) {
      if (state.isLoading) return;
      state.isLoading = true;
      if (elements.loadingOverlay) elements.loadingOverlay.classList.remove("d-none");
      if (elements.refreshSpinner) elements.refreshSpinner.classList.remove("d-none");
      Promise.resolve(callback()).finally(() => {
        state.isLoading = false;
        if (elements.loadingOverlay) elements.loadingOverlay.classList.add("d-none");
        if (elements.refreshSpinner) elements.refreshSpinner.classList.add("d-none");
      });
    }

    function buildQueryParams() {
      const params = new URLSearchParams();
      params.set("limit", String(state.limit));
      params.set("offset", String(state.offset));

      if (!elements.filterForm) return params;
      const formData = new FormData(elements.filterForm);

      const status = (formData.get("status") || "").toString().trim();
      const matchType = (formData.get("match_type") || "").toString().trim();
      const runId = (formData.get("run_id") || "").toString().trim();

      if (status) params.set("status", status);
      if (matchType) params.set("match_type", matchType);
      if (runId) params.set("run_id", runId);

      return params;
    }

    function fetchJSON(url, params, options = {}) {
      const requestUrl = params ? `${url}?${params.toString()}` : url;
      return fetch(requestUrl, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        ...options,
      }).then(async (response) => {
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

    function formatScore(score) {
      if (score === null || score === undefined) return "N/A";
      return (score * 100).toFixed(1) + "%";
    }

    function getScoreBadgeClass(score) {
      if (score === null || score === undefined) return "bg-secondary";
      if (score >= 0.95) return "bg-success";
      if (score >= 0.80) return "bg-warning text-dark";
      return "bg-secondary";
    }

    function getMatchTypeLabel(matchType) {
      const labels = {
        fuzzy_high: "High Confidence",
        fuzzy_review: "Review Band",
        fuzzy_low: "Low Score",
        deterministic_email: "Email Match",
        deterministic_phone: "Phone Match",
      };
      return labels[matchType] || matchType || "Unknown";
    }

    function getCandidateCardClass(score, matchType) {
      if (matchType === "fuzzy_high" || (score !== null && score >= 0.95)) {
        return "high-confidence";
      }
      if (matchType === "fuzzy_review" || (score !== null && score >= 0.80 && score < 0.95)) {
        return "review-band";
      }
      return "";
    }

    function escapeHtml(text) {
      if (text === null || text === undefined) return "";
      const div = document.createElement("div");
      div.textContent = String(text);
      return div.innerHTML;
    }

    function renderCandidates(candidates) {
      if (!elements.candidatesList) return;
      elements.candidatesList.innerHTML = "";

      if (!candidates || candidates.length === 0) {
        elements.candidatesList.innerHTML = `
          <div class="text-center py-5 text-muted">
            <p class="mb-0">No candidates matched your filters.</p>
          </div>
        `;
        return;
      }

      candidates.forEach((candidate) => {
        const card = document.createElement("div");
        card.className = `card mb-3 candidate-card ${getCandidateCardClass(candidate.score, candidate.match_type)}`;
        const scoreBadgeClass = getScoreBadgeClass(candidate.score);
        const scoreDisplay = formatScore(candidate.score);

        card.innerHTML = `
          <div class="card-body">
            <div class="d-flex justify-content-between align-items-start mb-2">
              <div class="flex-grow-1">
                <div class="d-flex align-items-center gap-2 mb-2">
                  <span class="badge ${scoreBadgeClass} score-badge">${scoreDisplay}</span>
                  <span class="badge bg-secondary">${getMatchTypeLabel(candidate.match_type)}</span>
                  <span class="badge bg-info">Run #${candidate.run_id}</span>
                </div>
                <h6 class="mb-1">
                  <strong>Primary:</strong> ${escapeHtml(candidate.primary_name || "Unknown")}
                </h6>
                <h6 class="mb-0">
                  <strong>Candidate:</strong> ${escapeHtml(candidate.candidate_name || "Unknown")}
                </h6>
              </div>
              <button type="button" class="btn btn-primary btn-sm review-candidate-btn" data-candidate-id="${candidate.id}">
                <i class="fas fa-eye me-1"></i> Review
              </button>
            </div>
            ${candidate.created_at ? `<small class="text-muted">Created: ${formatDateTime(candidate.created_at)}</small>` : ""}
          </div>
        `;
        elements.candidatesList.appendChild(card);
      });
    }

    function renderPagination(total, limit, offset) {
      if (!elements.pagination || !elements.paginationSummary) return;
      elements.pagination.innerHTML = "";
      const totalPages = Math.ceil(total / limit);
      const currentPage = Math.floor(offset / limit) + 1;

      if (totalPages <= 1) {
        elements.paginationSummary.textContent = `Showing ${total} candidate${total !== 1 ? "s" : ""}`;
        return;
      }

      elements.paginationSummary.textContent = `Showing ${offset + 1}–${Math.min(offset + limit, total)} of ${total} candidates`;

      const list = document.createElement("ul");
      list.className = "pagination pagination-sm mb-0 justify-content-end";

      function appendPage(page, label = null, disabled = false, active = false) {
        const li = document.createElement("li");
        li.className = `page-item ${disabled ? "disabled" : ""} ${active ? "active" : ""}`;
        const a = document.createElement("a");
        a.className = "page-link";
        a.href = "#";
        a.textContent = label || String(page);
        if (!disabled) {
          a.addEventListener("click", (event) => {
            event.preventDefault();
            if (page === currentPage) return;
            state.offset = (page - 1) * limit;
            loadCandidates();
          });
        }
        li.appendChild(a);
        list.appendChild(li);
      }

      appendPage(Math.max(1, currentPage - 1), "«", currentPage === 1);
      for (let page = 1; page <= totalPages; page += 1) {
        if (page === 1 || page === totalPages || Math.abs(page - currentPage) <= 2) {
          appendPage(page, null, false, page === currentPage);
        } else if (Math.abs(page - currentPage) === 3) {
          const ellipsis = document.createElement("li");
          ellipsis.className = "page-item disabled";
          ellipsis.innerHTML = `<span class="page-link">…</span>`;
          list.appendChild(ellipsis);
        }
      }
      appendPage(Math.min(totalPages, currentPage + 1), "»", currentPage === totalPages);
      elements.pagination.appendChild(list);
    }

    function renderStats(stats) {
      if (elements.statsCards.totalPending) {
        elements.statsCards.totalPending.textContent = stats.total_pending || 0;
      }
      if (elements.statsCards.reviewBand) {
        elements.statsCards.reviewBand.textContent = stats.total_review_band || 0;
      }
      if (elements.statsCards.highConfidence) {
        elements.statsCards.highConfidence.textContent = stats.total_high_confidence || 0;
      }
      if (elements.statsCards.agingOlder) {
        elements.statsCards.agingOlder.textContent = stats.aging_buckets?.[">48h"] || 0;
      }
    }

    function loadStats() {
      return fetchJSON(config.statsUrl)
        .then((data) => {
          renderStats(data);
        })
        .catch((err) => {
          console.error("Failed to load stats:", err);
        });
    }

    function loadCandidates() {
      return withLoading(() => {
        const params = buildQueryParams();
        return fetchJSON(config.apiBase, params)
          .then((data) => {
            renderCandidates(data.candidates || []);
            renderPagination(data.total || 0, data.limit || 100, data.offset || 0);
          })
          .catch((err) => {
            console.error("Failed to load candidates:", err);
            if (elements.candidatesList) {
              elements.candidatesList.innerHTML = `
                <div class="alert alert-danger" role="alert">
                  Failed to load candidates: ${escapeHtml(err.message)}
                </div>
              `;
            }
          });
      });
    }

    function renderFieldComparison(primary, candidate, features) {
      if (!primary || !candidate) return "";

      const primarySnapshot = primary.snapshot || {};
      const candidateSnapshot = candidate.snapshot || {};
      const allFields = new Set([...Object.keys(primarySnapshot), ...Object.keys(candidateSnapshot)]);

      let html = '<div class="table-responsive"><table class="table table-sm table-bordered">';
      html += '<thead><tr><th>Field</th><th>Primary</th><th>Candidate</th></tr></thead><tbody>';

      allFields.forEach((field) => {
        const primaryValue = primarySnapshot[field];
        const candidateValue = candidateSnapshot[field];
        const changed = primaryValue !== candidateValue;
        const highlight = features && features[field] ? "changed" : changed ? "changed" : "unchanged";

        html += `
          <tr class="field-diff ${highlight}">
            <td><strong>${escapeHtml(field)}</strong></td>
            <td>${escapeHtml(primaryValue !== null && primaryValue !== undefined ? String(primaryValue) : "—")}</td>
            <td>${escapeHtml(candidateValue !== null && candidateValue !== undefined ? String(candidateValue) : "—")}</td>
          </tr>
        `;
      });

      html += "</tbody></table></div>";
      return html;
    }

    function renderSurvivorshipPreview(preview) {
      if (!preview || !preview.decisions) return '<p class="text-muted">No survivorship preview available.</p>';

      let html = '<div class="table-responsive"><table class="table table-sm">';
      html += '<thead><tr><th>Field</th><th>Winner</th><th>Tier</th><th>Changed</th><th>Reason</th></tr></thead><tbody>';

      preview.decisions.forEach((decision) => {
        const winnerValue = decision.winner?.value !== null && decision.winner?.value !== undefined ? String(decision.winner.value) : "—";
        html += `
          <tr>
            <td><strong>${escapeHtml(decision.field_name)}</strong></td>
            <td>${escapeHtml(winnerValue)}</td>
            <td><span class="badge bg-secondary winner-badge">${escapeHtml(decision.winner?.tier || "—")}</span></td>
            <td>${decision.changed ? '<span class="badge bg-warning text-dark">Yes</span>' : '<span class="badge bg-success">No</span>'}</td>
            <td><small>${escapeHtml(decision.reason || "—")}</small></td>
          </tr>
        `;
      });

      html += "</tbody></table></div>";
      return html;
    }

    function renderTopFeatures(featuresJson) {
      if (!featuresJson || typeof featuresJson !== "object") return '<p class="text-muted">No feature data available.</p>';

      const features = [];
      if (featuresJson.name_similarity !== undefined) {
        features.push({ name: "Name Similarity", value: featuresJson.name_similarity });
      }
      if (featuresJson.dob_match !== undefined) {
        features.push({ name: "DOB Match", value: featuresJson.dob_match });
      }
      if (featuresJson.address_similarity !== undefined) {
        features.push({ name: "Address Similarity", value: featuresJson.address_similarity });
      }
      if (featuresJson.employer_similarity !== undefined) {
        features.push({ name: "Employer Similarity", value: featuresJson.employer_similarity });
      }

      if (features.length === 0) return '<p class="text-muted">No feature data available.</p>';

      let html = '<ul class="list-unstyled mb-0">';
      features.forEach((feature) => {
        const value = typeof feature.value === "number" ? (feature.value * 100).toFixed(1) + "%" : String(feature.value);
        html += `<li><strong>${escapeHtml(feature.name)}:</strong> ${escapeHtml(value)}</li>`;
      });
      html += "</ul>";
      return html;
    }

    function loadCandidateDetails(candidateId) {
      if (!elements.modalLoader || !elements.modalContent) return;

      elements.modalLoader.classList.remove("d-none");
      elements.modalContent.classList.add("d-none");
      state.currentCandidateId = candidateId;

      const url = config.candidateDetailsUrl.replace("0", String(candidateId));
      return fetchJSON(url)
        .then((data) => {
          // Render score badge
          if (elements.detailScoreBadge) {
            const score = data.score !== null && data.score !== undefined ? formatScore(data.score) : "N/A";
            const badgeClass = getScoreBadgeClass(data.score);
            elements.detailScoreBadge.className = `badge ${badgeClass} score-badge`;
            elements.detailScoreBadge.textContent = score;
          }

          // Render match type
          if (elements.detailMatchType) {
            elements.detailMatchType.textContent = getMatchTypeLabel(data.match_type);
          }

          // Render top features
          if (elements.detailTopFeatures) {
            elements.detailTopFeatures.innerHTML = renderTopFeatures(data.features_json);
          }

          // Render side-by-side comparison
          if (elements.detailPrimaryContact && elements.detailCandidateContact) {
            const primaryHtml = data.primary_contact
              ? `
                <div>
                  <p><strong>Name:</strong> ${escapeHtml(data.primary_contact.first_name || "")} ${escapeHtml(data.primary_contact.last_name || "")}</p>
                  <p><strong>ID:</strong> ${escapeHtml(data.primary_contact.id || "—")}</p>
                  ${data.primary_contact.updated_at ? `<p><small class="text-muted">Updated: ${formatDateTime(data.primary_contact.updated_at)}</small></p>` : ""}
                </div>
              `
              : '<p class="text-muted">No primary contact data.</p>';
            elements.detailPrimaryContact.innerHTML = primaryHtml;

            const candidateHtml = data.candidate_contact
              ? `
                <div>
                  <p><strong>Name:</strong> ${escapeHtml(data.candidate_contact.first_name || "")} ${escapeHtml(data.candidate_contact.last_name || "")}</p>
                  ${data.candidate_contact.id ? `<p><strong>ID:</strong> ${escapeHtml(data.candidate_contact.id)}</p>` : "<p><em>Staging record</em></p>"}
                  ${data.candidate_contact.updated_at ? `<p><small class="text-muted">Updated: ${formatDateTime(data.candidate_contact.updated_at)}</small></p>` : ""}
                </div>
              `
              : '<p class="text-muted">No candidate data.</p>';
            elements.detailCandidateContact.innerHTML = candidateHtml;
          }

          // Render field comparison
          if (elements.detailPrimaryContact && data.primary_contact && data.candidate_contact) {
            const comparisonHtml = renderFieldComparison(data.primary_contact, data.candidate_contact, data.features_json);
            if (elements.detailPrimaryContact) {
              const existing = elements.detailPrimaryContact.querySelector(".table-responsive");
              if (existing) existing.remove();
              elements.detailPrimaryContact.insertAdjacentHTML("beforeend", comparisonHtml);
            }
          }

          // Render survivorship preview
          if (elements.detailSurvivorshipPreview) {
            elements.detailSurvivorshipPreview.innerHTML = renderSurvivorshipPreview(data.survivorship_preview);
          }

          // Set candidate ID in form
          if (elements.actionCandidateId) {
            elements.actionCandidateId.value = String(candidateId);
          }

          elements.modalLoader.classList.add("d-none");
          elements.modalContent.classList.remove("d-none");
        })
        .catch((err) => {
          console.error("Failed to load candidate details:", err);
          if (elements.modalContent) {
            elements.modalContent.innerHTML = `
              <div class="alert alert-danger" role="alert">
                Failed to load candidate details: ${escapeHtml(err.message)}
              </div>
            `;
          }
        });
    }

    function submitAction(action) {
      if (!state.currentCandidateId) return;

      const candidateId = state.currentCandidateId;
      const notes = elements.actionNotes ? elements.actionNotes.value.trim() : "";

      let url;
      if (action === "merge") {
        url = config.mergeUrl.replace("0", String(candidateId));
      } else if (action === "reject") {
        url = config.rejectUrl.replace("0", String(candidateId));
      } else if (action === "defer") {
        url = config.deferUrl.replace("0", String(candidateId));
      } else {
        return;
      }

      if (elements.actionErrors) {
        elements.actionErrors.classList.add("d-none");
        elements.actionErrors.textContent = "";
      }

      const payload = {};
      if (notes) {
        payload.notes = notes;
      }

      return fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify(payload),
      })
        .then(async (response) => {
          if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.error || `Request failed with status ${response.status}`);
          }
          return response.json();
        })
        .then(() => {
          if (state.modalInstance) {
            state.modalInstance.hide();
          }
          loadCandidates();
          loadStats();
          if (elements.actionNotes) {
            elements.actionNotes.value = "";
          }
          showToast("Success", `Candidate ${action}ed successfully.`, "success");
        })
        .catch((err) => {
          console.error(`Failed to ${action} candidate:`, err);
          if (elements.actionErrors) {
            elements.actionErrors.textContent = err.message || `Failed to ${action} candidate.`;
            elements.actionErrors.classList.remove("d-none");
          }
        });
    }

    function showToast(title, message, type = "info") {
      if (!bootstrapToast) return;
      const toastContainer = document.querySelector(".toast-container") || createToastContainer();
      const toast = document.createElement("div");
      toast.className = "toast";
      toast.setAttribute("role", "alert");
      toast.setAttribute("aria-live", "assertive");
      toast.setAttribute("aria-atomic", "true");
      const bgClass = type === "success" ? "bg-success" : type === "error" ? "bg-danger" : "bg-info";
      toast.innerHTML = `
        <div class="toast-header ${bgClass} text-white">
          <strong class="me-auto">${escapeHtml(title)}</strong>
          <button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
        <div class="toast-body">
          ${escapeHtml(message)}
        </div>
      `;
      toastContainer.appendChild(toast);
      const toastInstance = bootstrapToast.getOrCreateInstance(toast);
      toastInstance.show();
      toast.addEventListener("hidden.bs.toast", () => {
        toast.remove();
      });
    }

    function createToastContainer() {
      const container = document.createElement("div");
      container.className = "toast-container position-fixed top-0 end-0 p-3";
      document.body.appendChild(container);
      return container;
    }

    function toggleAutoRefresh() {
      state.autoRefresh = !state.autoRefresh;
      if (elements.autoRefreshToggle) {
        elements.autoRefreshToggle.textContent = state.autoRefresh ? "Stop Auto Refresh" : "Auto Refresh";
        elements.autoRefreshToggle.classList.toggle("btn-primary", state.autoRefresh);
        elements.autoRefreshToggle.classList.toggle("btn-outline-secondary", !state.autoRefresh);
      }

      if (state.autoRefreshTimer) {
        clearInterval(state.autoRefreshTimer);
        state.autoRefreshTimer = null;
      }

      if (state.autoRefresh) {
        state.autoRefreshTimer = setInterval(() => {
          loadCandidates();
          loadStats();
        }, 30000); // 30 seconds
      }
    }

    // Event listeners
    if (elements.filterForm) {
      elements.filterForm.addEventListener("submit", (event) => {
        event.preventDefault();
        state.offset = 0;
        loadCandidates();
      });
    }

    if (elements.refreshButton) {
      elements.refreshButton.addEventListener("click", () => {
        loadCandidates();
        loadStats();
      });
    }

    if (elements.autoRefreshToggle) {
      elements.autoRefreshToggle.addEventListener("click", toggleAutoRefresh);
    }

    if (elements.candidatesList) {
      elements.candidatesList.addEventListener("click", (event) => {
        const btn = event.target.closest(".review-candidate-btn");
        if (btn) {
          const candidateId = parseInt(btn.dataset.candidateId, 10);
          if (candidateId && state.modalInstance) {
            loadCandidateDetails(candidateId).then(() => {
              state.modalInstance.show();
            });
          }
        }
      });
    }

    if (elements.actionMergeBtn) {
      elements.actionMergeBtn.addEventListener("click", () => {
        submitAction("merge");
      });
    }

    if (elements.actionRejectBtn) {
      elements.actionRejectBtn.addEventListener("click", () => {
        submitAction("reject");
      });
    }

    if (elements.actionDeferBtn) {
      elements.actionDeferBtn.addEventListener("click", () => {
        submitAction("defer");
      });
    }

    // Initial load
    loadCandidates();
    loadStats();
  });
})();
