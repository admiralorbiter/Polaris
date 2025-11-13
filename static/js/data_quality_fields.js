(function () {
  "use strict";

  const config = window.DATA_QUALITY_FIELDS_CONFIG;
  if (!config) {
    return;
  }

  let fieldConfig = {};
  let pendingChanges = {};
  let hasChanges = false;

  const elements = {
    refreshButton: document.getElementById("dq-fields-refresh-btn"),
    saveButton: document.getElementById("dq-fields-save-btn"),
    loading: document.getElementById("dq-fields-loading"),
    error: document.getElementById("dq-fields-error"),
    errorMessage: document.getElementById("dq-fields-error-message"),
    success: document.getElementById("dq-fields-success"),
    successMessage: document.getElementById("dq-fields-success-message"),
    entityTabs: document.querySelectorAll("#dq-fields-entity-tabs button[data-entity-type]"),
  };

  // Initialize on page load
  document.addEventListener("DOMContentLoaded", () => {
    if (!elements.refreshButton) {
      return;
    }

    setupEventListeners();
    loadFieldConfig();
  });

  function setupEventListeners() {
    // Refresh button
    if (elements.refreshButton) {
      elements.refreshButton.addEventListener("click", () => {
        loadFieldConfig();
      });
    }

    // Save button
    if (elements.saveButton) {
      elements.saveButton.addEventListener("click", () => {
        saveFieldConfig();
      });
    }

    // Entity tabs - render fields when tab is shown
    if (elements.entityTabs) {
      elements.entityTabs.forEach((tab) => {
        tab.addEventListener("shown.bs.tab", (e) => {
          const entityType = e.target.getAttribute("data-entity-type");
          if (entityType && fieldConfig[entityType]) {
            // Re-render fields when tab is shown (in case they weren't rendered initially)
            renderEntityFields(entityType);
          }
        });
      });
    }
  }

  function loadFieldConfig() {
    showLoading();
    hideError();
    hideSuccess();

    fetch(config.fieldConfigUrl)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
      })
      .then((data) => {
        fieldConfig = data.entity_types || {};
        pendingChanges = {};
        hasChanges = false;
        updateSaveButton();

        // Render all entity types that exist in the config
        const entityTypes = Object.keys(fieldConfig);
        if (entityTypes.length === 0) {
          showError("No field configuration found. Please check the API response.");
          hideLoading();
          return;
        }

        // Render all entity types
        entityTypes.forEach((entityType) => {
          renderEntityFields(entityType);
        });

        // Also render entity types that might be in the template but not in the config yet
        // This ensures all tabs have content, even if empty
        const allEntityTypes = ["volunteer", "contact", "student", "teacher", "event", "organization", "user"];
        allEntityTypes.forEach((entityType) => {
          const fieldsList = document.getElementById(`${entityType}-fields-list`);
          if (fieldsList && !fieldConfig[entityType]) {
            // Entity type exists in template but not in config - show empty state
            fieldsList.innerHTML = '<p class="text-muted">No fields configured for this entity type.</p>';
          }
        });

        hideLoading();
      })
      .catch((error) => {
        showError("Failed to load field configuration: " + error.message);
        hideLoading();
      });
  }

  function renderEntityFields(entityType) {
    const entityConfig = fieldConfig[entityType] || {};
    const fieldsList = document.getElementById(`${entityType}-fields-list`);
    if (!fieldsList) {
      return;
    }

    // Clear existing content
    fieldsList.innerHTML = "";

    // Get field names and sort them
    const fieldNames = Object.keys(entityConfig).sort();

    if (fieldNames.length === 0) {
      fieldsList.innerHTML = '<p class="text-muted">No fields available for this entity type.</p>';
      return;
    }

    // Create field items
    fieldNames.forEach((fieldName) => {
      const field = entityConfig[fieldName];
      if (!field) {
        return;
      }
      const fieldItem = createFieldItem(entityType, fieldName, field);
      if (fieldItem) {
        fieldsList.appendChild(fieldItem);
      }
    });
  }

  function createFieldItem(entityType, fieldName, field) {
    const div = document.createElement("div");
    div.className = "field-item mb-3 p-3 border rounded";
    div.dataset.entityType = entityType;
    div.dataset.fieldName = fieldName;

    const isEnabled = field.enabled !== false;
    const displayName = field.display_name || fieldName.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase());

    div.innerHTML = `
      <div class="d-flex justify-content-between align-items-center">
        <div class="flex-grow-1">
          <label class="form-label mb-0 fw-bold">${escapeHtml(displayName)}</label>
          <small class="text-muted d-block">${escapeHtml(fieldName)}</small>
        </div>
        <div class="form-check form-switch ms-3">
          <input
            class="form-check-input field-toggle"
            type="checkbox"
            role="switch"
            id="field-${entityType}-${fieldName}"
            ${isEnabled ? "checked" : ""}
            data-entity-type="${entityType}"
            data-field-name="${fieldName}"
          />
          <label class="form-check-label" for="field-${entityType}-${fieldName}">
            ${isEnabled ? "Enabled" : "Disabled"}
          </label>
        </div>
      </div>
    `;

    // Add event listener to toggle
    const toggle = div.querySelector(".field-toggle");
    if (toggle) {
      toggle.addEventListener("change", (e) => {
        const newValue = e.target.checked;
        const entityType = e.target.dataset.entityType;
        const fieldName = e.target.dataset.fieldName;

        // Update pending changes
        const key = `${entityType}.${fieldName}`;
        const currentValue = fieldConfig[entityType][fieldName].enabled !== false;

        if (newValue === currentValue) {
          // Reverting to original value
          delete pendingChanges[key];
        } else {
          // New change
          pendingChanges[key] = {
            entityType: entityType,
            fieldName: fieldName,
            isEnabled: newValue,
          };
        }

        // Update label
        const label = e.target.nextElementSibling;
        if (label) {
          label.textContent = newValue ? "Enabled" : "Disabled";
        }

        // Update hasChanges flag
        hasChanges = Object.keys(pendingChanges).length > 0;
        updateSaveButton();
      });
    }

    return div;
  }

  function saveFieldConfig() {
    if (!hasChanges || Object.keys(pendingChanges).length === 0) {
      return;
    }

    showLoading();
    hideError();
    hideSuccess();

    // Batch update all changes at once
    const changes = Object.values(pendingChanges);

    fetch(config.fieldConfigUpdateUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        changes: changes.map((change) => ({
          entity_type: change.entityType,
          field_name: change.fieldName,
          is_enabled: change.isEnabled,
        })),
      }),
    })
      .then((response) => {
        if (!response.ok) {
          return response.json().then((data) => {
            throw new Error(data.error || `HTTP error! status: ${response.status}`);
          });
        }
        return response.json();
      })
      .then((result) => {
        // Update fieldConfig with new values
        changes.forEach((change) => {
          if (fieldConfig[change.entityType] && fieldConfig[change.entityType][change.fieldName]) {
            fieldConfig[change.entityType][change.fieldName].enabled = change.isEnabled;
          }
        });

        // Clear pending changes
        pendingChanges = {};
        hasChanges = false;
        updateSaveButton();

        // Show success message
        showSuccess(
          `Field configuration updated successfully. ${result.updated_fields?.length || changes.length} field(s) updated. The dashboard will reflect these changes.`
        );

        // Reload after a short delay
        setTimeout(() => {
          loadFieldConfig();
        }, 2000);
      })
      .catch((error) => {
        showError("Failed to save field configuration: " + error.message);
        hideLoading();
      });
  }

  function updateSaveButton() {
    if (elements.saveButton) {
      elements.saveButton.disabled = !hasChanges;
      if (hasChanges) {
        elements.saveButton.classList.remove("btn-outline-primary");
        elements.saveButton.classList.add("btn-primary");
      } else {
        elements.saveButton.classList.remove("btn-primary");
        elements.saveButton.classList.add("btn-outline-primary");
      }
    }
  }

  function showLoading() {
    if (elements.loading) {
      elements.loading.classList.remove("d-none");
    }
  }

  function hideLoading() {
    if (elements.loading) {
      elements.loading.classList.add("d-none");
    }
  }

  function showError(message) {
    if (elements.error && elements.errorMessage) {
      elements.errorMessage.textContent = message;
      elements.error.classList.remove("d-none");
    }
  }

  function hideError() {
    if (elements.error) {
      elements.error.classList.add("d-none");
    }
  }

  function showSuccess(message) {
    if (elements.success && elements.successMessage) {
      elements.successMessage.textContent = message;
      elements.success.classList.remove("d-none");
      hideLoading();

      // Hide success message after 5 seconds
      setTimeout(() => {
        hideSuccess();
      }, 5000);
    }
  }

  function hideSuccess() {
    if (elements.success) {
      elements.success.classList.add("d-none");
    }
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }
})();

