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

      tbody.appendChild(row);
    });
    table.appendChild(tbody);

    // Clear container and add table
    elements.entityTableContainer.innerHTML = "";
    elements.entityTableContainer.appendChild(table);
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

