(function () {
  "use strict";

  const config = window.DATA_QUALITY_CONFIG;
  if (!config) {
    console.warn("DATA_QUALITY_CONFIG missing; Data quality samples will not initialize.");
    return;
  }

  let currentSamples = null;
  let currentStatistics = null;
  let currentEdgeCases = null;
  let currentEntityType = null;
  let currentSampleSize = 20;
  let selectedField = null; // Field to filter samples by

  // Expose to window for cross-script communication
  window.DATA_QUALITY_SAMPLES = {};
  Object.defineProperty(window.DATA_QUALITY_SAMPLES, 'selectedField', {
    set: function(value) {
      selectedField = value;
      if (currentEntityType && currentSamples) {
        // Re-render with field filter
        renderSamples();
      }
    },
    get: function() {
      return selectedField;
    },
    enumerable: true,
    configurable: true
  });

  const elements = {
    samplesEntitySelector: document.getElementById("dq-samples-entity-selector"),
    sampleSizeSelector: document.getElementById("dq-sample-size-selector"),
    samplesContainer: document.getElementById("dq-samples-container"),
    statisticsContainer: document.getElementById("dq-statistics-container"),
    edgeCasesContainer: document.getElementById("dq-edge-cases-container"),
    exportSamplesCsvBtn: document.getElementById("dq-export-samples-csv-btn"),
    exportSamplesJsonBtn: document.getElementById("dq-export-samples-json-btn"),
    loadingOverlay: document.getElementById("dq-loading-overlay"),
  };

  // Initialize on page load
  document.addEventListener("DOMContentLoaded", () => {
    if (!elements.samplesEntitySelector) {
      console.warn("Data quality samples elements not found.");
      return;
    }

    setupEventListeners();

    // Sync entity selector with metrics tab when samples tab is shown
    const samplesTab = document.getElementById("samples-tab");
    if (samplesTab) {
      samplesTab.addEventListener("shown.bs.tab", () => {
        // Check if there's a selected entity in the metrics tab
        const metricsEntitySelector = document.getElementById("dq-entity-selector");
        if (metricsEntitySelector && metricsEntitySelector.value) {
          elements.samplesEntitySelector.value = metricsEntitySelector.value;
          handleEntityChange();
        }
      });
    }

  });

  function setupEventListeners() {
    // Entity selector change
    if (elements.samplesEntitySelector) {
      elements.samplesEntitySelector.addEventListener("change", handleEntityChange);
    }

    // Sample size selector change
    if (elements.sampleSizeSelector) {
      elements.sampleSizeSelector.addEventListener("change", handleSampleSizeChange);
    }

    // Export buttons
    if (elements.exportSamplesCsvBtn) {
      elements.exportSamplesCsvBtn.addEventListener("click", (e) => {
        e.preventDefault();
        exportSamples("csv");
      });
    }

    if (elements.exportSamplesJsonBtn) {
      elements.exportSamplesJsonBtn.addEventListener("click", (e) => {
        e.preventDefault();
        exportSamples("json");
      });
    }

    // Tab change handlers for sub-tabs
    const sampleRecordsTab = document.getElementById("sample-records-tab");
    const statisticsTab = document.getElementById("statistics-tab");
    const edgeCasesTab = document.getElementById("edge-cases-tab");

    // Use Bootstrap 5 tab events
    const sampleRecordsPane = document.getElementById("sample-records-pane");
    const statisticsPane = document.getElementById("statistics-pane");
    const edgeCasesPane = document.getElementById("edge-cases-pane");

    if (sampleRecordsPane) {
      sampleRecordsPane.addEventListener("shown.bs.tab", () => {
        if (currentEntityType && currentSamples) {
          renderSamples();
        }
      });
    }

    if (statisticsPane) {
      statisticsPane.addEventListener("shown.bs.tab", () => {
        if (currentEntityType && !currentStatistics) {
          loadStatistics();
        } else if (currentStatistics) {
          renderStatistics();
        }
      });
    }

    if (edgeCasesPane) {
      edgeCasesPane.addEventListener("shown.bs.tab", () => {
        if (currentEntityType && !currentEdgeCases) {
          loadEdgeCases();
        } else if (currentEdgeCases) {
          renderEdgeCases();
        }
      });
    }

    // Also listen to tab button clicks as fallback
    if (sampleRecordsTab) {
      sampleRecordsTab.addEventListener("click", () => {
        if (currentEntityType && currentSamples) {
          setTimeout(() => renderSamples(), 100);
        }
      });
    }

    if (statisticsTab) {
      statisticsTab.addEventListener("click", () => {
        if (currentEntityType && !currentStatistics) {
          setTimeout(() => loadStatistics(), 100);
        } else if (currentStatistics) {
          setTimeout(() => renderStatistics(), 100);
        }
      });
    }

    if (edgeCasesTab) {
      edgeCasesTab.addEventListener("click", () => {
        if (currentEntityType && !currentEdgeCases) {
          setTimeout(() => loadEdgeCases(), 100);
        } else if (currentEdgeCases) {
          setTimeout(() => renderEdgeCases(), 100);
        }
      });
    }
  }

  function handleEntityChange() {
    const entityType = elements.samplesEntitySelector.value;
    if (!entityType) {
      currentEntityType = null;
      currentSamples = null;
      currentStatistics = null;
      currentEdgeCases = null;
      clearContainers();
      return;
    }

    currentEntityType = entityType;
    loadSamples();
  }

  function handleSampleSizeChange() {
    currentSampleSize = parseInt(elements.sampleSizeSelector.value, 10);
    if (currentEntityType) {
      loadSamples();
    }
  }

  function clearContainers() {
    if (elements.samplesContainer) {
      elements.samplesContainer.innerHTML = '<p class="text-muted text-center">Select an entity above to view sample records.</p>';
    }
    if (elements.statisticsContainer) {
      elements.statisticsContainer.innerHTML = '<p class="text-muted text-center">Select an entity above to view statistical summaries.</p>';
    }
    if (elements.edgeCasesContainer) {
      elements.edgeCasesContainer.innerHTML = '<p class="text-muted text-center">Select an entity above to view edge cases.</p>';
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

  function getApiUrl(urlTemplate, entityType) {
    return urlTemplate.replace("__ENTITY_TYPE__", entityType);
  }

  function buildQueryParams() {
    const params = new URLSearchParams();
    if (config.organizationId) {
      params.append("organization_id", config.organizationId);
    }
    return params.toString();
  }

  async function loadSamples() {
    if (!currentEntityType) return;

    showLoading();
    try {
      const url = getApiUrl(config.samplesUrl, currentEntityType);
      const params = buildQueryParams();
      const fullUrl = `${url}?sample_size=${currentSampleSize}${params ? `&${params}` : ""}`;

      const response = await fetch(fullUrl);
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      currentSamples = data;
      renderSamples();
    } catch (error) {
      console.error("Error loading samples:", error);
      if (elements.samplesContainer) {
        elements.samplesContainer.innerHTML = `<div class="alert alert-danger">Error loading samples: ${error.message}</div>`;
      }
    } finally {
      hideLoading();
    }
  }

  async function loadStatistics() {
    if (!currentEntityType) return;

    showLoading();
    try {
      const url = getApiUrl(config.statisticsUrl, currentEntityType);
      const params = buildQueryParams();
      const fullUrl = `${url}${params ? `?${params}` : ""}`;

      const response = await fetch(fullUrl);
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      currentStatistics = data;
      renderStatistics();
    } catch (error) {
      console.error("Error loading statistics:", error);
      if (elements.statisticsContainer) {
        elements.statisticsContainer.innerHTML = `<div class="alert alert-danger">Error loading statistics: ${error.message}</div>`;
      }
    } finally {
      hideLoading();
    }
  }

  async function loadEdgeCases() {
    if (!currentEntityType) return;

    showLoading();
    try {
      const url = getApiUrl(config.edgeCasesUrl, currentEntityType);
      const params = buildQueryParams();
      const fullUrl = `${url}?limit=20${params ? `&${params}` : ""}`;

      const response = await fetch(fullUrl);
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      currentEdgeCases = data;
      renderEdgeCases();
    } catch (error) {
      console.error("Error loading edge cases:", error);
      if (elements.edgeCasesContainer) {
        elements.edgeCasesContainer.innerHTML = `<div class="alert alert-danger">Error loading edge cases: ${error.message}</div>`;
      }
    } finally {
      hideLoading();
    }
  }

  function renderSamples() {
    if (!elements.samplesContainer || !currentSamples) return;

    if (!currentSamples.samples || currentSamples.samples.length === 0) {
      elements.samplesContainer.innerHTML = '<p class="text-muted text-center">No samples available for this entity.</p>';
      return;
    }

    // Filter samples by selected field if specified
    let filteredSamples = currentSamples.samples;
    let fieldFilterNote = "";
    if (selectedField) {
      // Filter to show samples that have this field populated
      filteredSamples = currentSamples.samples.filter(sample => {
        return sample.data && sample.data[selectedField] !== null && sample.data[selectedField] !== undefined && sample.data[selectedField] !== "";
      });
      if (filteredSamples.length < currentSamples.samples.length) {
        fieldFilterNote = ` <span class="badge bg-info">Filtered by field: ${selectedField}</span>`;
      }
    }

    let html = `
      <div class="mb-3">
        <p class="text-muted">
          Showing <strong>${filteredSamples.length}</strong> of <strong>${currentSamples.total_records}</strong> total records.
          Samples are intelligently selected to show diverse data patterns.${fieldFilterNote}
          ${selectedField ? `<button class="btn btn-sm btn-outline-secondary ms-2" id="clear-field-filter-btn">Clear Filter</button>` : ''}
        </p>
      </div>
      <div class="table-responsive">
        <table class="table table-hover table-striped" id="dq-samples-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Data</th>
              <th>Completeness</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
    `;

    filteredSamples.forEach((sample) => {
      const completenessBadge = getCompletenessBadge(sample.completeness_score, sample.completeness_level);
      const edgeCaseBadge = sample.is_edge_case
        ? '<span class="badge bg-warning">Edge Case</span>'
        : "";

      html += `
        <tr data-sample-id="${sample.id}" class="${sample.is_edge_case ? "table-warning" : ""}">
          <td>${sample.id}</td>
          <td>
            <div class="sample-data-preview">
              ${renderSampleDataPreview(sample.data)}
            </div>
            <div class="sample-data-full" style="display: none;">
              ${renderSampleDataFull(sample.data)}
            </div>
          </td>
          <td>
            <div class="completeness-score">${sample.completeness_score.toFixed(1)}%</div>
            ${completenessBadge}
          </td>
          <td>${edgeCaseBadge}</td>
          <td>
            <button class="btn btn-sm btn-outline-primary toggle-details" data-sample-id="${sample.id}">
              <i class="fas fa-chevron-down"></i> Details
            </button>
          </td>
        </tr>
      `;
    });

    html += `
          </tbody>
        </table>
      </div>
    `;

    elements.samplesContainer.innerHTML = html;

    // Add click handler for clear filter button
    const clearFilterBtn = document.getElementById("clear-field-filter-btn");
    if (clearFilterBtn) {
      clearFilterBtn.addEventListener("click", () => {
        selectedField = null;
        window.DATA_QUALITY_SAMPLES.selectedField = null;
        renderSamples();
      });
    }

    // Add click handlers for expandable rows
    document.querySelectorAll(".toggle-details").forEach((btn) => {
      btn.addEventListener("click", function () {
        const sampleId = this.getAttribute("data-sample-id");
        const row = this.closest("tr");
        const preview = row.querySelector(".sample-data-preview");
        const full = row.querySelector(".sample-data-full");
        const icon = this.querySelector("i");

        if (!preview || !full) return;

        if (full.style.display === "none") {
          preview.style.display = "none";
          full.style.display = "block";
          if (icon) {
            icon.classList.remove("fa-chevron-down");
            icon.classList.add("fa-chevron-up");
          }
          this.textContent = " Hide Details";
        } else {
          preview.style.display = "block";
          full.style.display = "none";
          if (icon) {
            icon.classList.remove("fa-chevron-up");
            icon.classList.add("fa-chevron-down");
          }
          this.textContent = " Details";
        }
      });
    });

    // Add sorting functionality to table headers
    const table = document.getElementById("dq-samples-table");
    if (table) {
      const headers = table.querySelectorAll("thead th");
      headers.forEach((header, index) => {
        if (index < headers.length - 1) { // Don't make Actions column sortable
          header.style.cursor = "pointer";
          header.classList.add("sortable");
          header.addEventListener("click", () => {
            sortTable(table, index);
          });
        }
      });
    }
  }

  function renderSampleDataPreview(data) {
    const keys = Object.keys(data).slice(0, 3);
    return keys
      .map((key) => {
        const value = data[key];
        return value !== null && value !== undefined ? `<strong>${key}:</strong> ${String(value).substring(0, 30)}` : "";
      })
      .filter(Boolean)
      .join(", ");
  }

  function renderSampleDataFull(data) {
    let html = '<dl class="row mb-0">';
    Object.entries(data).forEach(([key, value]) => {
      html += `
        <dt class="col-sm-3">${key}:</dt>
        <dd class="col-sm-9">${value !== null && value !== undefined ? String(value) : "<em>null</em>"}</dd>
      `;
    });
    html += "</dl>";
    return html;
  }

  function renderStatistics() {
    if (!elements.statisticsContainer || !currentStatistics) return;

    if (!currentStatistics.statistics || Object.keys(currentStatistics.statistics).length === 0) {
      elements.statisticsContainer.innerHTML = '<p class="text-muted text-center">No statistics available for this entity.</p>';
      return;
    }

    let html = '<div class="row g-3">';

    Object.entries(currentStatistics.statistics).forEach(([fieldName, stat]) => {
      html += `
        <div class="col-md-6 col-lg-4">
          <div class="card h-100">
            <div class="card-header">
              <h6 class="mb-0">${fieldName}</h6>
            </div>
            <div class="card-body">
              <div class="mb-2">
                <small class="text-muted">Completeness:</small>
                <div class="progress" style="height: 20px;">
                  <div class="progress-bar" role="progressbar"
                       style="width: ${((stat.non_null_count / stat.total_count) * 100).toFixed(1)}%">
                    ${((stat.non_null_count / stat.total_count) * 100).toFixed(1)}%
                  </div>
                </div>
              </div>
              <div class="small">
                <div><strong>Total:</strong> ${stat.total_count}</div>
                <div><strong>Non-null:</strong> ${stat.non_null_count}</div>
                <div><strong>Null:</strong> ${stat.null_count}</div>
                <div><strong>Unique values:</strong> ${stat.unique_values}</div>
              </div>
      `;

      if (stat.most_common_values && stat.most_common_values.length > 0) {
        html += `
          <div class="mt-2">
            <small class="text-muted">Most common:</small>
            <ul class="list-unstyled mb-0 small">
        `;
        stat.most_common_values.slice(0, 5).forEach((item) => {
          html += `<li>${item.value} (${item.count})</li>`;
        });
        html += `</ul></div>`;
      }

      if (stat.min_value !== null || stat.max_value !== null || stat.avg_value !== null) {
        html += `<div class="mt-2 small">`;
        if (stat.min_value !== null) html += `<div><strong>Min:</strong> ${stat.min_value}</div>`;
        if (stat.max_value !== null) html += `<div><strong>Max:</strong> ${stat.max_value}</div>`;
        if (stat.avg_value !== null) html += `<div><strong>Avg:</strong> ${stat.avg_value.toFixed(2)}</div>`;
        html += `</div>`;
      }

      html += `
            </div>
          </div>
        </div>
      `;
    });

    html += "</div>";
    elements.statisticsContainer.innerHTML = html;
  }

  function renderEdgeCases() {
    if (!elements.edgeCasesContainer || !currentEdgeCases) return;

    if (!currentEdgeCases.edge_cases || currentEdgeCases.edge_cases.length === 0) {
      elements.edgeCasesContainer.innerHTML = '<p class="text-muted text-center">No edge cases found for this entity.</p>';
      return;
    }

    let html = `
      <div class="mb-3">
        <p class="text-muted">
          Found <strong>${currentEdgeCases.edge_cases.length}</strong> edge cases that may need attention.
        </p>
      </div>
      <div class="table-responsive">
        <table class="table table-hover table-striped">
          <thead>
            <tr>
              <th>ID</th>
              <th>Data</th>
              <th>Completeness</th>
              <th>Issues</th>
            </tr>
          </thead>
          <tbody>
    `;

    currentEdgeCases.edge_cases.forEach((edgeCase) => {
      const completenessBadge = getCompletenessBadge(edgeCase.completeness_score, edgeCase.completeness_level);

      html += `
        <tr class="table-warning">
          <td>${edgeCase.id}</td>
          <td>
            <div class="sample-data-preview">
              ${renderSampleDataPreview(edgeCase.data)}
            </div>
          </td>
          <td>
            <div class="completeness-score">${edgeCase.completeness_score.toFixed(1)}%</div>
            ${completenessBadge}
          </td>
          <td>
            <ul class="list-unstyled mb-0">
              ${edgeCase.edge_case_reasons.map((reason) => `<li><span class="badge bg-warning">${reason}</span></li>`).join("")}
            </ul>
          </td>
        </tr>
      `;
    });

    html += `
          </tbody>
        </table>
      </div>
    `;

    elements.edgeCasesContainer.innerHTML = html;
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

  function exportSamples(format) {
    if (!currentEntityType) {
      alert("Please select an entity type first.");
      return;
    }

    const url = getApiUrl(config.exportSamplesUrl, currentEntityType);
    const params = buildQueryParams();
    const fullUrl = `${url}?format=${format}&sample_size=${currentSampleSize}${params ? `&${params}` : ""}`;

    window.location.href = fullUrl;
  }

  function sortTable(table, columnIndex) {
    const tbody = table.querySelector("tbody");
    const rows = Array.from(tbody.querySelectorAll("tr"));
    const isAscending = table.dataset.sortColumn === String(columnIndex) && table.dataset.sortDirection === "asc";

    // Remove sort indicators from all headers
    table.querySelectorAll("thead th").forEach((th) => {
      th.classList.remove("sort-asc", "sort-desc");
    });

    // Sort rows
    rows.sort((a, b) => {
      const aCell = a.cells[columnIndex];
      const bCell = b.cells[columnIndex];

      let aValue = aCell.textContent.trim();
      let bValue = bCell.textContent.trim();

      // Try to parse as number
      const aNum = parseFloat(aValue);
      const bNum = parseFloat(bValue);

      if (!isNaN(aNum) && !isNaN(bNum)) {
        return isAscending ? bNum - aNum : aNum - bNum;
      }

      // String comparison
      return isAscending ? bValue.localeCompare(aValue) : aValue.localeCompare(bValue);
    });

    // Clear tbody and re-append sorted rows
    tbody.innerHTML = "";
    rows.forEach((row) => tbody.appendChild(row));

    // Update sort indicators
    const header = table.querySelectorAll("thead th")[columnIndex];
    table.dataset.sortColumn = String(columnIndex);
    table.dataset.sortDirection = isAscending ? "desc" : "asc";
    header.classList.add(isAscending ? "sort-desc" : "sort-asc");
  }
})();
