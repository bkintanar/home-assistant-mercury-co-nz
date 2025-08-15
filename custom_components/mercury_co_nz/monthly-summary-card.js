// monthly-summary-card.js
// Mercury Energy Monthly Summary Card for Home Assistant

class MercuryMonthlySummaryCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });

    // Configuration tracking
    this.config = null;
    this.configSet = false;
    this.pendingConfig = null;
    this.configRetryTimeout = null;
  }

  // Helper method for entity validation and retrieval
  getEntity() {
    if (!this._hass || !this.config.entity) return null;
    return this._hass.states[this.config.entity];
  }

  // Helper method to check if entity is available (very permissive to prevent config errors)
  isEntityAvailable() {
    if (!this.config || !this.config.entity) return false;

    const entity = this.getEntity();
    if (!entity) return false;

    // Be more permissive - only reject if truly missing, not just temporarily unavailable
    // This prevents configuration errors during Home Assistant startup/restart
    return true; // If entity exists at all, consider it "available" for config purposes
  }

  // Helper method to check if entity has monthly summary data
  hasMonthlySummaryData() {
    const entity = this.getEntity();
    if (!entity || !entity.attributes) return false;

    // Check if entity has monthly summary data
    return (
      entity.attributes.monthly_usage_cost !== undefined ||
      entity.attributes.monthly_usage_consumption !== undefined ||
      entity.attributes.monthly_days_remaining !== undefined
    );
  }

    // Helper method to format disclaimer text from Mercury API
  formatDisclaimerText(disclaimerText) {
    if (!disclaimerText) {
      // Fallback text if API content is not available
      return [
        "*Your actual electricity total for this billing period may vary. The amount shown is based on your electricity usage to date but may not include the last two days.",
        "**Your actual bill total may vary at the end of this billing period. The amount shown is based on an estimate for your electricity usage."
      ];
    }

    // Split by \r\n\r\n to separate the two disclaimers
    return disclaimerText.split(/\r?\n\r?\n/).filter(text => text.trim());
  }

  // Helper method to detect if we're in dark mode
  isDarkMode() {
    // Check Home Assistant theme variables
    const style = getComputedStyle(document.body);
    const bgColor = style.getPropertyValue('--primary-background-color').trim();
    const isDark = bgColor.includes('#1') || bgColor.includes('rgb(1') ||
                   style.getPropertyValue('--state-icon-color').includes('#fff');

    return isDark ||
           document.body.hasAttribute('data-theme') &&
           document.body.getAttribute('data-theme').includes('dark');
  }

  // Apply theme-specific adjustments
  applyThemeAdjustments() {
    const card = this.shadowRoot.querySelector('ha-card');
    if (!card) return;

    const isDark = this.isDarkMode();

    if (isDark) {
      card.setAttribute('data-dark-mode', 'true');
    } else {
      card.removeAttribute('data-dark-mode');
    }
  }

  // Helper method for date formatting
  formatDate(dateString, options = {}) {
    if (!dateString) return '';

    try {
      const date = new Date(dateString);
      const defaultOptions = {
        day: 'numeric',
        month: 'short',
        year: 'numeric'
      };
      return date.toLocaleDateString("en-NZ", { ...defaultOptions, ...options });
    } catch (error) {
      console.warn('Date formatting error:', error);
      return dateString;
    }
  }

  // Helper method to extract projected bill amount from note
  extractProjectedBill(note) {
    if (!note) return null;

    // Look for patterns like "$207" or "bill $207"
    const match = note.match(/\$(\d+(?:\.\d{2})?)/);
    return match ? parseFloat(match[1]) : null;
  }

  async setConfig(config) {
    // Very permissive validation to prevent configuration errors
    if (!config) {
      console.warn('Mercury Monthly Summary: No config provided, using defaults...');
      config = { entity: '' }; // Provide minimal default config
    }

    if (typeof config !== 'object') {
      console.warn('Mercury Monthly Summary: Invalid config type, creating default...');
      config = { entity: config?.entity || '' }; // Try to salvage entity if possible
    }

    // Don't require entity to be set immediately - Home Assistant might be loading
    if (!config.entity) {
      console.log('Mercury Monthly Summary: No entity defined yet, will retry when available...');
      // Store the config but don't fail
      this.pendingConfig = config;

      // Set up a more patient retry mechanism
      if (!this.configRetryTimeout) {
        this.configRetryTimeout = setTimeout(() => {
          this.configRetryTimeout = null;
          if (this.pendingConfig && this.pendingConfig.entity) {
            console.log('Mercury Monthly Summary: Retrying configuration with entity:', this.pendingConfig.entity);
            this.setConfig(this.pendingConfig);
          }
        }, 5000); // Wait longer for HA to fully load
      }

      // Set a basic config so the card doesn't show "configuration error"
      this.config = {
        name: 'Monthly Summary',
        entity: '',
        show_progress_bar: true,
        ...config
      };
      this.configSet = true;
      return;
    }

    // Clear any pending retries
    if (this.configRetryTimeout) {
      clearTimeout(this.configRetryTimeout);
      this.configRetryTimeout = null;
    }
    this.pendingConfig = null;

    this.config = {
      name: 'Monthly Summary',
      entity: config.entity,
      show_progress_bar: true,
      ...config
    };

    this.configSet = true;
    console.log('Mercury Monthly Summary: Configuration set successfully with entity:', this.config.entity);

    // Don't immediately render - wait for hass to be available
    if (this._hass && this.isEntityAvailable()) {
      this.render();
    } else if (this._hass) {
      // If hass is available but entity data isn't ready, retry after a short delay
      setTimeout(() => {
        if (this.isEntityAvailable()) {
          this.render();
        }
      }, 1000);
    }
  }

  set hass(hass) {
    const oldHass = this._hass;
    this._hass = hass;

    // If we have a pending config due to hard refresh, try to apply it now
    if (!this.config && this.pendingConfig && hass) {
      console.log('Mercury Monthly Summary: Attempting to apply pending configuration with hass available');
      this.setConfig(this.pendingConfig);
      return;
    }

    // If config isn't set yet, don't try to render
    if (!this.config || !this.configSet) {
      return;
    }

    // Initial setup - render when hass becomes available and entity has data
    if (!oldHass && this.isEntityAvailable()) {
      this.render();
      return;
    }

    // If no old hass but entity isn't available yet, set up a retry mechanism
    if (!oldHass) {
      setTimeout(() => {
        if (this.isEntityAvailable()) {
          this.render();
        }
      }, 2000);
      return;
    }

    const oldEntity = oldHass.states[this.config.entity];
    const newEntity = hass.states[this.config.entity];

    // Handle entity availability changes
    const wasUnavailable = !oldEntity || oldEntity.state === 'unavailable' || oldEntity.state === 'unknown';
    const isNowAvailable = newEntity && newEntity.state !== 'unavailable' && newEntity.state !== 'unknown';

    // If entity became available after being unavailable, do a full render
    if (wasUnavailable && isNowAvailable && this.isEntityAvailable()) {
      this.render();
      return;
    }

    // Check if entity data actually changed
    if (oldEntity && newEntity &&
        oldEntity.last_changed !== newEntity.last_changed &&
        this.hasMonthlySummaryData()) {
      this.render();
    }
  }

  render() {
    if (!this.config || !this._hass || !this.configSet) {
      // Show a temporary state if we're waiting for configuration during hard refresh
      if (this.pendingConfig) {
        this.showWaitingForConfigState();
      }
      return;
    }

    // If no entity is configured, show helpful message instead of error
    if (!this.config.entity) {
      this.showConfigurationNeededState();
      return;
    }

    // Check if entity exists and is available
    if (!this.isEntityAvailable()) {
      this.showWaitingState();
      return;
    }

    const entity = this.getEntity();

    // If entity is available but doesn't have monthly summary data yet, show loading
    if (!this.hasMonthlySummaryData()) {
      this.showDataLoadingState();
      return;
    }

    // Render the card with data
    this.renderCard(entity);

    // Apply theme adjustments after rendering
    setTimeout(() => this.applyThemeAdjustments(), 0);
  }

    renderCard(entity) {
    const { attributes } = entity;

    // Extract data with fallbacks
    const usageCost = attributes.monthly_usage_cost || 0;
    const usageConsumption = attributes.monthly_usage_consumption || 0;
    const daysRemaining = attributes.monthly_days_remaining || 0;
    const progressPercent = attributes.monthly_billing_progress_percent || 0;
    const startDate = attributes.monthly_billing_start_date || '';
    const endDate = attributes.monthly_billing_end_date || '';
    const projectedBillNote = attributes.monthly_projected_bill_note || '';

    // Extract projected bill amount from note
    const projectedBill = this.extractProjectedBill(projectedBillNote);

    // Get content text from Mercury API
    const disclaimerText = attributes.content_disclaimer_text || '';
    const disclaimerParts = this.formatDisclaimerText(disclaimerText);
    const monthlyDescription = attributes.content_monthly_summary_description || 'The electricity you\'ve used in this billing period';

    // Format dates
    const startDateFormatted = this.formatDate(startDate, { day: 'numeric', month: 'short', year: 'numeric' });
    const endDateFormatted = this.formatDate(endDate, { day: 'numeric', month: 'short', year: 'numeric' });

    this.shadowRoot.innerHTML = `
      ${this.getStyles()}

      <ha-card>
        <div class="card-content">
          <div class="header">
            <div class="title-row">
              <h3>${this.config.name}</h3>
            </div>
            <div class="subtitle">${monthlyDescription}</div>
          </div>

          <div class="usage-summary">
            <div class="cost-row">
              <span class="cost">$${usageCost.toFixed(0)}</span><span class="asterisk">*</span>
            </div>
            <div class="consumption">${usageConsumption.toFixed(0)} kWh</div>
          </div>

          ${this.config.show_progress_bar ? this.renderProgressBar(progressPercent) : ''}

          <div class="period-info">
            <div class="period-dates">${startDateFormatted} - ${endDateFormatted}</div>
            <div class="days-remaining">${daysRemaining} days left</div>
          </div>

          ${projectedBill ? `
            <div class="projected-bill">
              <div class="projected-content">
                <div class="plug-icon">🔌</div>
                <span>Projected electricity bill $${projectedBill.toFixed(0)}**</span>
              </div>
            </div>
          ` : ''}

          <div class="footer-notes">
            ${disclaimerParts.map(part => `<div class="note">${part.trim()}</div>`).join('')}
          </div>
        </div>
      </ha-card>
    `;
  }

  renderProgressBar(progressPercent) {
    // Ensure progress is between 0 and 100
    const clampedProgress = Math.min(100, Math.max(0, progressPercent));

    return `
      <div class="progress-container">
        <div class="progress-bar">
          <div class="progress-fill" style="width: ${clampedProgress}%;"></div>
        </div>
      </div>
    `;
  }

  showWaitingState() {
    if (!this.shadowRoot) return;
    this.shadowRoot.innerHTML = `
      <ha-card>
        <div style="padding: 20px; text-align: center;">
          <div style="margin-bottom: 10px;">⏳ Waiting for Entity...</div>
          <div style="font-size: 0.8em; opacity: 0.7;">Mercury Energy entity is loading or unavailable</div>
        </div>
      </ha-card>
    `;
  }

  showDataLoadingState() {
    if (!this.shadowRoot) return;
    this.shadowRoot.innerHTML = `
      <ha-card>
        <div style="padding: 20px; text-align: center;">
          <div style="margin-bottom: 10px;">📊 Loading Monthly Summary...</div>
          <div style="font-size: 0.8em; opacity: 0.7;">Mercury Energy monthly data is being fetched</div>
        </div>
      </ha-card>
    `;
  }

  showWaitingForConfigState() {
    if (!this.shadowRoot) return;
    this.shadowRoot.innerHTML = `
      <ha-card>
        <div style="padding: 20px; text-align: center;">
          <div style="margin-bottom: 10px;">⚙️ Initializing Card...</div>
          <div style="font-size: 0.8em; opacity: 0.7;">Setting up Mercury Energy monthly summary configuration</div>
        </div>
      </ha-card>
    `;
  }

  showConfigurationNeededState() {
    if (!this.shadowRoot) return;
    this.shadowRoot.innerHTML = `
      <ha-card>
        <div style="padding: 20px; text-align: center;">
          <div style="margin-bottom: 10px;">⚙️ Configuration Required</div>
          <div style="font-size: 0.8em; opacity: 0.7; margin-bottom: 15px;">Please configure an entity for this Mercury Energy monthly summary</div>
          <div style="font-size: 0.7em; background: var(--secondary-background-color, #f5f5f5); padding: 10px; border-radius: 4px; text-align: left;">
            <strong>Example configuration:</strong><br/>
            type: custom:mercury-monthly-summary-card<br/>
            entity: sensor.mercury_nz_energy_usage
          </div>
        </div>
      </ha-card>
    `;
  }

  getStyles() {
    return `
      <style>
        :host {
          display: block;
        }

        ha-card {
          background: var(--ha-card-background);
          border-radius: var(--ha-card-border-radius);
          box-shadow: var(--ha-card-box-shadow);
          padding: 0;
          overflow: hidden;
          border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color, transparent));
        }

        .card-content {
          padding: 24px;
        }

        .header {
          margin-bottom: 20px;
        }

        .title-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 8px;
        }

        .header h3 {
          margin: 0;
          color: var(--primary-text-color);
          font-size: 18px;
          font-weight: 600;
          letter-spacing: -0.5px;
        }

        .info-icon {
          color: var(--secondary-text-color);
          font-size: 16px;
          opacity: 0.7;
        }

        .subtitle {
          color: var(--secondary-text-color);
          font-size: 14px;
          margin: 0;
          line-height: 1.3;
        }

        .usage-summary {
          margin-bottom: 20px;
        }

        .cost-row {
          margin-bottom: 4px;
        }

        .cost {
          font-size: 48px;
          font-weight: 700;
          color: var(--primary-text-color);
          line-height: 1;
        }

        .asterisk {
          font-size: 28px;
          color: var(--secondary-text-color);
          margin-left: 2px;
          vertical-align: top;
        }

        .consumption {
          font-size: 18px;
          font-weight: 500;
          color: var(--primary-text-color);
          line-height: 1;
        }

        .progress-container {
          margin-bottom: 20px;
        }

        .progress-bar {
          width: 100%;
          height: 12px;
          background-color: var(--card-background-color, #e0e0e0);
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 6px;
          overflow: hidden;
          position: relative;
        }

        .progress-fill {
          height: 100%;
          background: #ffeb3b;
          border-radius: 6px;
          transition: width 0.3s ease;
          position: relative;
        }

        /* Dark mode progress bar */
        ha-card[data-dark-mode="true"] .progress-bar,
        ha-card[data-theme*="dark"] .progress-bar,
        :host([dark-mode]) .progress-bar {
          background-color: var(--card-background-color, #2d2d2d);
          border: 1px solid var(--divider-color, #3d3d3d);
        }

        .period-info {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 16px;
          font-size: 14px;
        }

        .period-dates {
          color: var(--primary-text-color);
          font-weight: 500;
        }

        .days-remaining {
          color: var(--primary-text-color);
          font-weight: 500;
        }

        .projected-bill {
          background: var(--card-background-color, var(--ha-card-background, #fafafa));
          border: 1px solid var(--divider-color, var(--primary-color, #03a9f4));
          border-radius: 8px;
          padding: 12px 16px;
          margin-bottom: 16px;
          /* Add subtle accent for better visibility */
          box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        }

        /* Dark mode specific styling */
        ha-card[data-dark-mode="true"] .projected-bill,
        ha-card[data-theme*="dark"] .projected-bill,
        :host([dark-mode]) .projected-bill {
          background: var(--card-background-color, #1e1e1e);
          border: 1px solid var(--accent-color, var(--primary-color, #03a9f4));
          box-shadow: 0 1px 3px rgba(255, 255, 255, 0.05);
        }

        .projected-content {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 14px;
          color: var(--primary-text-color);
          font-weight: 500;
        }

        /* Ensure projected bill text is always visible */
        .projected-bill span {
          color: var(--primary-text-color) !important;
        }

        /* Dark mode text enhancement */
        ha-card[data-dark-mode="true"] .projected-bill span,
        ha-card[data-theme*="dark"] .projected-bill span,
        :host([dark-mode]) .projected-bill span {
          color: var(--primary-text-color, #ffffff) !important;
        }

        .plug-icon {
          font-size: 16px;
        }

        .footer-notes {
          font-size: 12px;
          color: var(--secondary-text-color);
          line-height: 1.4;
        }

        .note {
          margin-bottom: 8px;
        }

        .note:last-child {
          margin-bottom: 0;
        }

        /* Responsive design */
        @media (max-width: 480px) {
          .card-content {
            padding: 16px;
          }

          .cost {
            font-size: 36px;
          }

          .consumption {
            font-size: 16px;
          }

          .period-info {
            flex-direction: column;
            gap: 8px;
            align-items: flex-start;
          }
        }
      </style>
    `;
  }

  getCardSize() {
    return 3;
  }

  // Cleanup when card is removed
  disconnectedCallback() {
    // Clear any pending configuration retries
    if (this.configRetryTimeout) {
      clearTimeout(this.configRetryTimeout);
      this.configRetryTimeout = null;
    }
  }
}

// Register the card (prevent re-registration during hard refresh)
if (!customElements.get('mercury-monthly-summary-card')) {
  customElements.define('mercury-monthly-summary-card', MercuryMonthlySummaryCard);
  console.log('Mercury Monthly Summary Card: Custom element registered successfully');
} else {
  console.log('Mercury Monthly Summary Card: Custom element already registered');
}

// Add to Home Assistant's custom card registry
window.customCards = window.customCards || [];

// Prevent duplicate entries in customCards array
const existingCard = window.customCards.find(card => card.type === 'mercury-monthly-summary-card');
if (!existingCard) {
  window.customCards.push({
    type: 'mercury-monthly-summary-card',
    name: 'Mercury Monthly Summary Card',
    description: 'Monthly billing summary card for Mercury Energy NZ',
    preview: false,
    documentationURL: 'https://github.com/bkintanar/home-assistant-mercury-co-nz'
  });
  console.log('Mercury Monthly Summary Card: Added to Home Assistant custom cards registry');
}

console.info(
  '%c MERCURY-MONTHLY-SUMMARY-CARD %c v1.0.0 ',
  'color: orange; font-weight: bold; background: black',
  'color: white; font-weight: bold; background: dimgray'
);
