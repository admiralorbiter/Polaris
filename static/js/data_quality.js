(function () {
  "use strict";

  const config = window.DATA_QUALITY_CONFIG;
  if (!config) {
    console.warn("DATA_QUALITY_CONFIG missing; Data quality dashboard will not initialize.");
    return;
  }

  let currentMetrics = null;
  let currentEntityDetails = null;
  let currentOrganizationId = config.organizationId;
  let currentEntityType = null;
  let currentFieldName = null;
  let fieldStatisticsLoaded = false;

  const elements = {
    refreshButton: document.getElementById("dq-refresh-btn"),
    exportCsvButton: document.getElementById("dq-export-csv-btn"),
    exportJsonButton: document.getElementById("dq-export-json-btn"),
    filterForm: document.getElementById("dq-filter-form"),
    resetButton: document.getElementById("dq-reset-btn"),
    organizationFilter: document.getElementById("filter-organization"),
    healthScoreValue: document.getElementById("dq-health-score-value"),
    healthScoreCircle: document.getElementById("dq-health-score-circle"),
    healthScoreDescription: document.getElementById("dq-health-score-description"),
    timestamp: document.getElementById("dq-timestamp"),
    entityCards: document.getElementById("dq-entity-cards"),
    entitySelector: document.getElementById("dq-entity-selector"),
    entityTableContainer: document.getElementById("dq-entity-table-container"),
    loadingOverlay: document.getElementById("dq-loading-overlay"),
  };

  // Initialize on page load
  document.addEventListener("DOMContentLoaded", () => {
    if (!elements.refreshButton) {
      console.warn("Data quality dashboard elements not found.");
      return;
    }

    setupEventListeners();
    loadMetrics();
  });

  function setupEventListeners() {
    // Refresh button
    if (elements.refreshButton) {
      elements.refreshButton.addEventListener("click", () => {
        loadMetrics();
      });
    }

    // Export buttons
    if (elements.exportCsvButton) {
      elements.exportCsvButton.addEventListener("click", (e) => {
        e.preventDefault();
        exportMetrics("csv");
      });
    }

    if (elements.exportJsonButton) {
      elements.exportJsonButton.addEventListener("click", (e) => {
        e.preventDefault();
        exportMetrics("json");
      });
    }

    // Filter form
    if (elements.filterForm) {
      elements.filterForm.addEventListener("submit", (e) => {
        e.preventDefault();
        applyFilters();
      });

      // Auto-apply filters on change
      if (elements.organizationFilter) {
        elements.organizationFilter.addEventListener("change", () => {
          applyFilters();
        });
      }
    }

    // Reset button
    if (elements.resetButton) {
      elements.resetButton.addEventListener("click", () => {
        resetFilters();
      });
    }

    // Entity selector
    if (elements.entitySelector) {
      elements.entitySelector.addEventListener("change", (e) => {
        const entityType = e.target.value;
        if (entityType) {
          loadEntityDetails(entityType);
        } else {
          clearEntityDetails();
        }
      });
    }

    // Back to metrics button
    const backToMetricsBtn = document.getElementById("dq-back-to-metrics-btn");
    if (backToMetricsBtn) {
      backToMetricsBtn.addEventListener("click", (e) => {
        e.preventDefault();
        backToMetrics();
      });
    }

    // Tab change handlers for field exploration tabs
    const fieldSamplesTab = document.getElementById("field-samples-tab");
    const fieldStatisticsTab = document.getElementById("field-statistics-tab");

    // Lazy load statistics when tab is clicked
    if (fieldStatisticsTab) {
      fieldStatisticsTab.addEventListener("shown.bs.tab", (e) => {
        if (currentEntityType && currentFieldName && !fieldStatisticsLoaded) {
          loadFieldStatistics(currentEntityType, currentFieldName);
          fieldStatisticsLoaded = true;
        }
      });
    }

    if (fieldSamplesTab) {
      fieldSamplesTab.addEventListener("shown.bs.tab", () => {
        if (currentEntityType && currentFieldName) {
          loadFieldSamples(currentEntityType, currentFieldName);
        }
      });
    }

    if (fieldStatisticsTab) {
      fieldStatisticsTab.addEventListener("shown.bs.tab", () => {
        if (currentEntityType && currentFieldName) {
          loadFieldStatistics(currentEntityType, currentFieldName);
        }
      });
    }
  }

  function showLoading() {
    if (elements.loadingOverlay) {
      elements.loadingOverlay.style.display = "flex";
    }
  }

  function hideLoading() {
    if (elements.loadingOverlay) {
      elements.loadingOverlay.style.display = "none";
    }
  }

  function getOrganizationId() {
    if (config.isSuperAdmin && elements.organizationFilter) {
      const orgId = elements.organizationFilter.value;
      return orgId ? parseInt(orgId, 10) : null;
    }
    return config.organizationId;
  }

  function loadMetrics() {
    showLoading();

    const orgId = getOrganizationId();
    const url = orgId
      ? `${config.metricsUrl}?organization_id=${orgId}`
      : config.metricsUrl;

    fetch(url)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
      })
      .then((data) => {
        currentMetrics = data;
        renderMetrics(data);
        hideLoading();
      })
      .catch((error) => {
        console.error("Error loading metrics:", error);
        showError("Failed to load metrics. Please try again.");
        hideLoading();
      });
  }

  function renderMetrics(metrics) {
    // Update health score
    if (elements.healthScoreValue) {
      elements.healthScoreValue.textContent = metrics.overall_health_score.toFixed(1);
    }

    // Update health score circle color
    if (elements.healthScoreCircle) {
      const score = metrics.overall_health_score;
      elements.healthScoreCircle.className = "health-score-circle";
      if (score >= 80) {
        elements.healthScoreCircle.classList.add("health-score-good");
      } else if (score >= 50) {
        elements.healthScoreCircle.classList.add("health-score-warning");
      } else {
        elements.healthScoreCircle.classList.add("health-score-critical");
      }
    }

    // Update description
    if (elements.healthScoreDescription) {
      const score = metrics.overall_health_score;
      let description = "";
      if (score >= 80) {
        description = "Excellent data quality! Most fields are complete.";
      } else if (score >= 50) {
        description = "Good data quality, but some fields need attention.";
      } else {
        description = "Data quality needs improvement. Many fields are incomplete.";
      }
      elements.healthScoreDescription.textContent = description;
    }

    // Update timestamp
    if (elements.timestamp) {
      const timestamp = new Date(metrics.timestamp);
      elements.timestamp.textContent = `Last updated: ${timestamp.toLocaleString()}`;
    }

    // Render entity cards
    renderEntityCards(metrics.entity_metrics);
  }

  function renderEntityCards(entityMetrics) {
    if (!elements.entityCards) {
      return;
    }

    elements.entityCards.innerHTML = "";

    entityMetrics.forEach((entity) => {
      const card = createEntityCard(entity);
      elements.entityCards.appendChild(card);
    });
  }

  function createEntityCard(entity) {
    const col = document.createElement("div");
    col.className = "col-sm-6 col-lg-4 col-xl-3";

    const card = document.createElement("div");
    card.className = "card shadow-sm entity-card";
    card.style.cursor = "pointer";
    card.addEventListener("click", () => {
      if (elements.entitySelector) {
        elements.entitySelector.value = entity.entity_type;
        loadEntityDetails(entity.entity_type);
      }
    });

    const cardBody = document.createElement("div");
    cardBody.className = "card-body";

    // Entity type header
    const header = document.createElement("h3");
    header.className = "h6 mb-2";
    header.textContent = formatEntityType(entity.entity_type);

    // Total records
    const totalRecords = document.createElement("p");
    totalRecords.className = "text-muted small mb-2";
    totalRecords.textContent = `${entity.total_records.toLocaleString()} total records`;

    // Completeness percentage
    const completeness = document.createElement("div");
    completeness.className = "mb-2";
    const completenessBar = document.createElement("div");
    completenessBar.className = "progress";
    completenessBar.style.height = "20px";
    const completenessBarFill = document.createElement("div");
    completenessBarFill.className = "progress-bar";
    const percentage = entity.overall_completeness;
    completenessBarFill.style.width = `${percentage}%`;
    completenessBarFill.setAttribute("role", "progressbar");
    completenessBarFill.setAttribute("aria-valuenow", percentage);
    completenessBarFill.setAttribute("aria-valuemin", "0");
    completenessBarFill.setAttribute("aria-valuemax", "100");
    completenessBarFill.textContent = `${percentage.toFixed(1)}%`;

    // Set color based on percentage
    if (percentage >= 80) {
      completenessBarFill.classList.add("bg-success");
    } else if (percentage >= 50) {
      completenessBarFill.classList.add("bg-warning");
    } else {
      completenessBarFill.classList.add("bg-danger");
    }

    completenessBar.appendChild(completenessBarFill);
    completeness.appendChild(completenessBar);

    // Key metrics
    const keyMetrics = document.createElement("div");
    keyMetrics.className = "mt-2";
    if (entity.key_metrics && Object.keys(entity.key_metrics).length > 0) {
      const metricsList = document.createElement("ul");
      metricsList.className = "list-unstyled small mb-0";
      Object.entries(entity.key_metrics).forEach(([key, value]) => {
        const li = document.createElement("li");
        if (value && typeof value === "object" && "percentage" in value) {
          li.textContent = `${formatFieldName(key)}: ${value.percentage.toFixed(1)}%`;
        } else {
          li.textContent = `${formatFieldName(key)}: ${value}`;
        }
        metricsList.appendChild(li);
      });
      keyMetrics.appendChild(metricsList);
    } else {
      const noMetrics = document.createElement("p");
      noMetrics.className = "text-muted small mb-0";
      noMetrics.textContent = "No key metrics available";
      keyMetrics.appendChild(noMetrics);
    }

    cardBody.appendChild(header);
    cardBody.appendChild(totalRecords);
    cardBody.appendChild(completeness);
    cardBody.appendChild(keyMetrics);
    card.appendChild(cardBody);
    col.appendChild(card);

    return col;
  }

  function loadEntityDetails(entityType) {
    currentEntityType = entityType;
    // Hide field exploration if showing
    const explorationCard = document.getElementById("dq-field-exploration");
    if (explorationCard) explorationCard.style.display = "none";

    showLoading();

    const orgId = getOrganizationId();
    let url = config.entityMetricsUrl.replace("__ENTITY_TYPE__", entityType);
    if (orgId) {
      url += `?organization_id=${orgId}`;
    }

    fetch(url)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
      })
      .then((data) => {
        currentEntityDetails = data;
        renderEntityDetails(data);
        hideLoading();
      })
      .catch((error) => {
        console.error("Error loading entity details:", error);
        showError("Failed to load entity details. Please try again.");
        hideLoading();
      });
  }

  function renderEntityDetails(entity) {
    if (!elements.entityTableContainer) {
      return;
    }

    const table = document.createElement("table");
    table.className = "table table-striped table-hover";
    table.setAttribute("id", "dq-entity-table");

    // Table header
    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");
    ["Field Name", "Total Records", "With Value", "Without Value", "Completeness", "Status"].forEach(
      (header) => {
        const th = document.createElement("th");
        th.textContent = header;
        headerRow.appendChild(th);
      }
    );
    thead.appendChild(headerRow);
    table.appendChild(thead);

    // Table body
    const tbody = document.createElement("tbody");
    entity.fields.forEach((field) => {
      const row = document.createElement("tr");
      row.style.cursor = "pointer";

      // Field name
      const fieldNameCell = document.createElement("td");
      fieldNameCell.textContent = formatFieldName(field.field_name);
      row.appendChild(fieldNameCell);

      // Total records
      const totalCell = document.createElement("td");
      totalCell.textContent = field.total_records.toLocaleString();
      row.appendChild(totalCell);

      // With value
      const withValueCell = document.createElement("td");
      withValueCell.textContent = field.records_with_value.toLocaleString();
      row.appendChild(withValueCell);

      // Without value
      const withoutValueCell = document.createElement("td");
      withoutValueCell.textContent = field.records_without_value.toLocaleString();
      row.appendChild(withoutValueCell);

      // Completeness
      const completenessCell = document.createElement("td");
      const completenessBar = document.createElement("div");
      completenessBar.className = "progress";
      completenessBar.style.height = "20px";
      const completenessBarFill = document.createElement("div");
      completenessBarFill.className = "progress-bar";
      const percentage = field.completeness_percentage;
      completenessBarFill.style.width = `${percentage}%`;
      completenessBarFill.textContent = `${percentage.toFixed(1)}%`;

      // Set color based on status
      if (field.status === "good") {
        completenessBarFill.classList.add("bg-success");
      } else if (field.status === "warning") {
        completenessBarFill.classList.add("bg-warning");
      } else {
        completenessBarFill.classList.add("bg-danger");
      }

      completenessBar.appendChild(completenessBarFill);
      completenessCell.appendChild(completenessBar);
      row.appendChild(completenessCell);

      // Status
      const statusCell = document.createElement("td");
      const statusBadge = document.createElement("span");
      statusBadge.className = "badge";
      if (field.status === "good") {
        statusBadge.classList.add("bg-success");
      } else if (field.status === "warning") {
        statusBadge.classList.add("bg-warning", "text-dark");
      } else {
        statusBadge.classList.add("bg-danger");
      }
      statusBadge.textContent = field.status.charAt(0).toUpperCase() + field.status.slice(1);
      statusCell.appendChild(statusBadge);
      row.appendChild(statusCell);

      // Make entire row clickable
      row.addEventListener("click", (e) => {
        // Don't trigger if clicking on a link or button
        if (e.target.tagName === "A" || e.target.tagName === "BUTTON" || e.target.closest("a") || e.target.closest("button")) {
          return;
        }
        viewFieldExploration(entity.entity_type, field.field_name, field);
      });

      tbody.appendChild(row);
    });
    table.appendChild(tbody);

    // Clear container and add table
    elements.entityTableContainer.innerHTML = "";
    elements.entityTableContainer.appendChild(table);
  }

  function viewFieldExploration(entityType, fieldName, fieldData) {
    // Store current state
    currentEntityType = entityType;
    currentFieldName = fieldName;
    // Reset loaded flags when switching fields
    fieldStatisticsLoaded = false;

    // Hide metrics table, show field exploration
    const metricsCard = document.getElementById("dq-entity-details");
    const explorationCard = document.getElementById("dq-field-exploration");

    if (metricsCard) metricsCard.style.display = "none";
    if (explorationCard) explorationCard.style.display = "block";

    // Update field exploration header
    const titleEl = document.getElementById("dq-field-exploration-title");
    const descEl = document.getElementById("dq-field-description");

    if (titleEl) {
      titleEl.textContent = `Field: ${formatFieldName(fieldName)}`;
    }

    if (descEl && fieldData) {
      descEl.innerHTML = `
        <strong>Completeness:</strong> ${fieldData.completeness_percentage.toFixed(1)}%
        (${fieldData.records_with_value.toLocaleString()} of ${fieldData.total_records.toLocaleString()} records have this field populated)
        <span class="badge ${fieldData.status === 'good' ? 'bg-success' : fieldData.status === 'warning' ? 'bg-warning text-dark' : 'bg-danger'} ms-2">
          ${fieldData.status.charAt(0).toUpperCase() + fieldData.status.slice(1)}
        </span>
      `;
    }

    // Load only samples initially (lazy load statistics and edge cases when tabs are clicked)
    loadFieldSamples(entityType, fieldName);
  }

  function backToMetrics() {
    // Hide field exploration, show metrics table
    const metricsCard = document.getElementById("dq-entity-details");
    const explorationCard = document.getElementById("dq-field-exploration");

    if (metricsCard) metricsCard.style.display = "block";
    if (explorationCard) explorationCard.style.display = "none";

    // Clear field state
    currentFieldName = null;
  }

  async function loadFieldSamples(entityType, fieldName) {
    const container = document.getElementById("dq-field-samples-container");
    if (!container) return;

    container.innerHTML = '<p class="text-muted text-center">Loading sample records...</p>';
    showLoading();

    try {
      const orgId = getOrganizationId();
      let url = config.fieldSamplesUrl
        .replace("__ENTITY_TYPE__", entityType)
        .replace("__FIELD_NAME__", encodeURIComponent(fieldName));
      url += `?sample_size=20`;
      if (orgId) {
        url += `&organization_id=${orgId}`;
      }

      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      renderFieldSamples(data, fieldName);
    } catch (error) {
      console.error("Error loading field samples:", error);
      container.innerHTML = `<div class="alert alert-danger">Error loading samples: ${error.message}</div>`;
    } finally {
      hideLoading();
    }
  }

  async function loadFieldStatistics(entityType, fieldName) {
    const container = document.getElementById("dq-field-statistics-container");
    if (!container) return;

    container.innerHTML = '<p class="text-muted text-center">Loading statistics...</p>';

    try {
      const orgId = getOrganizationId();
      let url = config.fieldStatisticsUrl
        .replace("__ENTITY_TYPE__", entityType)
        .replace("__FIELD_NAME__", encodeURIComponent(fieldName));
      if (orgId) {
        url += `?organization_id=${orgId}`;
      }

      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      renderFieldStatistics(data);
    } catch (error) {
      console.error("Error loading field statistics:", error);
      container.innerHTML = `<div class="alert alert-danger">Error loading statistics: ${error.message}</div>`;
    }
  }


  function renderFieldSamples(data, fieldName) {
    const container = document.getElementById("dq-field-samples-container");
    if (!container) return;

    if (!data.samples || data.samples.length === 0) {
      container.innerHTML = '<p class="text-muted text-center">No sample records found for this field.</p>';
      return;
    }

    let html = `
      <div class="mb-3">
        <p class="text-muted">
          Showing <strong>${data.sample_size}</strong> sample records that have the <strong>${formatFieldName(fieldName)}</strong> field populated.
        </p>
      </div>
      <div class="table-responsive">
        <table class="table table-hover table-striped">
          <thead>
            <tr>
              <th>ID</th>
              <th><strong>${formatFieldName(fieldName)}</strong></th>
              <th>Other Data</th>
              <th>Completeness</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
    `;

    data.samples.forEach((sample) => {
      const fieldValue = sample.data[fieldName] || "<em>null</em>";
      const completenessBadge = getCompletenessBadge(sample.completeness_score, sample.completeness_level);

      // Get other fields for preview (exclude the selected field)
      const otherFields = Object.entries(sample.data)
        .filter(([key]) => key !== fieldName)
        .slice(0, 2)
        .map(([key, val]) => `<strong>${formatFieldName(key)}:</strong> ${val !== null && val !== undefined ? String(val).substring(0, 30) : '<em>null</em>'}`)
        .join(", ");

      html += `
        <tr>
          <td>${sample.id}</td>
          <td><strong class="text-primary">${fieldValue}</strong></td>
          <td><small class="text-muted">${otherFields || '<em>No other data</em>'}</small></td>
          <td>
            <div class="completeness-score">${sample.completeness_score.toFixed(1)}%</div>
            ${completenessBadge}
          </td>
          <td>
            <button class="btn btn-sm btn-outline-primary toggle-field-details" data-sample-id="${sample.id}">
              <i class="fas fa-chevron-down"></i> <span class="btn-text">Details</span>
            </button>
          </td>
        </tr>
        <tr id="field-details-${sample.id}" style="display: none;">
          <td colspan="5">
            <div class="p-3 bg-light rounded">
              <dl class="row mb-0">
                ${Object.entries(sample.data).map(([key, val]) => `
                  <dt class="col-sm-3">${formatFieldName(key)}:</dt>
                  <dd class="col-sm-9">${val !== null && val !== undefined ? String(val) : '<em>null</em>'}</dd>
                `).join("")}
              </dl>
            </div>
          </td>
        </tr>
      `;
    });

    html += `
          </tbody>
        </table>
      </div>
    `;

    container.innerHTML = html;

    // Add click handlers for expandable rows
    document.querySelectorAll(".toggle-field-details").forEach((btn) => {
      btn.addEventListener("click", function () {
        const sampleId = this.getAttribute("data-sample-id");
        const detailsRow = document.getElementById(`field-details-${sampleId}`);
        const icon = this.querySelector("i");
        const textSpan = this.querySelector(".btn-text");

        if (!icon) {
          // Icon was removed, recreate button content
          if (detailsRow && (detailsRow.style.display === "none" || detailsRow.style.display === "")) {
            this.innerHTML = '<i class="fas fa-chevron-up"></i> <span class="btn-text">Hide Details</span>';
          } else {
            this.innerHTML = '<i class="fas fa-chevron-down"></i> <span class="btn-text">Details</span>';
          }
          return;
        }

        if (detailsRow && (detailsRow.style.display === "none" || detailsRow.style.display === "")) {
          detailsRow.style.display = "table-row";
          icon.classList.remove("fa-chevron-down");
          icon.classList.add("fa-chevron-up");
          if (textSpan) {
            textSpan.textContent = "Hide Details";
          }
        } else {
          if (detailsRow) {
            detailsRow.style.display = "none";
          }
          icon.classList.remove("fa-chevron-up");
          icon.classList.add("fa-chevron-down");
          if (textSpan) {
            textSpan.textContent = "Details";
          }
        }
      });
    });
  }

  function renderFieldStatistics(data) {
    const container = document.getElementById("dq-field-statistics-container");
    if (!container) return;

    if (!data.statistics) {
      container.innerHTML = '<p class="text-muted text-center">No statistics available for this field.</p>';
      return;
    }

    const stat = data.statistics;
    const completenessPercent = ((stat.non_null_count / stat.total_count) * 100).toFixed(1);

    let html = `
      <div class="row">
        <div class="col-md-6">
          <div class="card mb-3">
            <div class="card-header">
              <h6 class="mb-0">Completeness</h6>
            </div>
            <div class="card-body">
              <div class="mb-2">
                <div class="progress" style="height: 30px;">
                  <div class="progress-bar ${stat.non_null_count / stat.total_count >= 0.8 ? 'bg-success' : stat.non_null_count / stat.total_count >= 0.5 ? 'bg-warning' : 'bg-danger'}"
                       role="progressbar" style="width: ${completenessPercent}%">
                    ${completenessPercent}%
                  </div>
                </div>
              </div>
              <div class="small">
                <div><strong>Total records:</strong> ${stat.total_count.toLocaleString()}</div>
                <div><strong>With value:</strong> ${stat.non_null_count.toLocaleString()}</div>
                <div><strong>Without value:</strong> ${stat.null_count.toLocaleString()}</div>
                <div><strong>Unique values:</strong> ${stat.unique_values.toLocaleString()}</div>
              </div>
            </div>
          </div>
        </div>
    `;

    if (stat.most_common_values && stat.most_common_values.length > 0) {
      html += `
        <div class="col-md-6">
          <div class="card mb-3">
            <div class="card-header">
              <h6 class="mb-0">Most Common Values</h6>
            </div>
            <div class="card-body">
              <ul class="list-unstyled mb-0">
                ${stat.most_common_values.slice(0, 10).map((item) => `
                  <li class="mb-2">
                    <strong>${item.value}</strong>
                    <span class="badge bg-secondary">${item.count}</span>
                    <div class="progress mt-1" style="height: 5px;">
                      <div class="progress-bar" role="progressbar" style="width: ${(item.count / stat.non_null_count * 100)}%"></div>
                    </div>
                  </li>
                `).join("")}
              </ul>
            </div>
          </div>
        </div>
      `;
    }

    if (stat.min_value !== null || stat.max_value !== null || stat.avg_value !== null) {
      html += `
        <div class="col-md-6">
          <div class="card mb-3">
            <div class="card-header">
              <h6 class="mb-0">Numeric Statistics</h6>
            </div>
            <div class="card-body">
              ${stat.min_value !== null ? `<div><strong>Min:</strong> ${stat.min_value}</div>` : ''}
              ${stat.max_value !== null ? `<div><strong>Max:</strong> ${stat.max_value}</div>` : ''}
              ${stat.avg_value !== null ? `<div><strong>Average:</strong> ${stat.avg_value.toFixed(2)}</div>` : ''}
            </div>
          </div>
        </div>
      `;
    }

    html += `</div>`;
    container.innerHTML = html;
  }


  function getCompletenessBadge(score, level) {
    if (level === "high") {
      return '<span class="badge bg-success">Good</span>';
    } else if (level === "medium") {
      return '<span class="badge bg-warning">Warning</span>';
    } else {
      return '<span class="badge bg-danger">Critical</span>';
    }
  }

  function clearEntityDetails() {
    if (elements.entityTableContainer) {
      elements.entityTableContainer.innerHTML =
        '<p class="text-muted text-center">Select an entity above to view field-level completeness metrics.</p>';
    }
  }

  function applyFilters() {
    loadMetrics();
    // Reload entity details if one is selected
    if (elements.entitySelector && elements.entitySelector.value) {
      loadEntityDetails(elements.entitySelector.value);
    }
  }

  function resetFilters() {
    if (elements.filterForm) {
      elements.filterForm.reset();
    }
    if (elements.organizationFilter && config.isSuperAdmin) {
      elements.organizationFilter.value = "";
    }
    applyFilters();
  }

  function exportMetrics(format) {
    const orgId = getOrganizationId();
    const url = orgId
      ? `${config.exportUrl}?format=${format}&organization_id=${orgId}`
      : `${config.exportUrl}?format=${format}`;

    window.location.href = url;
  }

  function formatEntityType(entityType) {
    return entityType
      .split("_")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");
  }

  function formatFieldName(fieldName) {
    return fieldName
      .split("_")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");
  }

  function showError(message) {
    // Create a simple error notification
    const alert = document.createElement("div");
    alert.className = "alert alert-danger alert-dismissible fade show";
    alert.setAttribute("role", "alert");
    alert.innerHTML = `
      ${message}
      <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;

    // Insert at the top of the dashboard
    const dashboard = document.querySelector(".data-quality-dashboard");
    if (dashboard) {
      dashboard.insertBefore(alert, dashboard.firstChild);
    }
  }
})();
