// Mercury Energy Monthly Summary Card for Home Assistant
// Modern LitElement implementation of the monthly summary card

import { LitElement, html, css } from 'https://unpkg.com/lit@3.1.0/index.js?module';
import { mercuryCardStyles, mercuryColors } from './mercury-lit-styles.js';
import { mercuryLitCore } from './mercury-lit-core.js';

class MercuryMonthlySummaryCard extends LitElement {
  static styles = [
    mercuryCardStyles,
    css`
      /* Monthly-specific info icon styles */
      .info-icon {
        color: var(--secondary-text-color);
        font-size: 16px;
        opacity: 0.7;
      }
    `
  ];

  static properties = {
    hass: { type: Object },
    config: { type: Object },
    _entity: { type: Object, state: true }
  };

  constructor() {
    super();
    // Apply common core functionality using composition
    Object.assign(this, mercuryLitCore);
    this.initializeBase();

    // Monthly-specific properties
    this.CHART_COLORS = { ...this.CHART_COLORS, ...mercuryColors };
  }

  setConfig(config) {
    this.config = this.setConfigBase(config, 'Monthly Summary');
    this.config.show_progress_bar = config.show_progress_bar !== false;

    console.log('Mercury Monthly Summary: Configuration set successfully with entity:', this.config.entity);
  }

  connectedCallback() {
    super.connectedCallback();
    this._detectDarkMode();
  }

  // Called when hass or entity data changes
  updated(changedProps) {
    super.updated(changedProps);

    // Handle hass changes
    if (changedProps.has('hass') && this.hass) {
      const oldEntity = changedProps.get('hass')?.states[this.config?.entity];
      const newEntity = this._getEntity();

      // Only update if entity data actually changed
      const entityChanged = !oldEntity ||
        !newEntity ||
        oldEntity.last_changed !== newEntity.last_changed ||
        JSON.stringify(oldEntity.attributes) !== JSON.stringify(newEntity.attributes);

      if (entityChanged) {
        this._entity = newEntity;

        // Apply theme adjustments after render
        this._applyThemeAdjustments();
      }
    }
  }

  // _getEntity() inherited from mercuryLitCore

  // _isEntityAvailable() inherited from mercuryLitCore

  // Helper method to check if entity has monthly summary data
  _hasMonthlySummaryData() {
    const entity = this._getEntity();
    if (!entity || !entity.attributes) return false;

    return (
      entity.attributes.monthly_usage_cost !== undefined ||
      entity.attributes.monthly_usage_consumption !== undefined ||
      entity.attributes.monthly_days_remaining !== undefined
    );
  }

  // _formatDate() inherited from mercuryLitCore

  // Helper method to extract projected bill amount from note
  _extractProjectedBill(note) {
    if (!note) return null;

    // Look for patterns like "$207" or "bill $207"
    const match = note.match(/\$(\d+(?:\.\d{2})?)/);
    return match ? parseFloat(match[1]) : null;
  }

  // Helper method to format disclaimer text from Mercury API
  _formatDisclaimerText(disclaimerText) {
    if (!disclaimerText) {
      // Fallback text if API content is not available
      return [];
    }

    // Split by \r\n\r\n to separate the two disclaimers
    return disclaimerText.split(/\r?\n\r?\n/).filter(text => text.trim());
  }

  // _detectDarkMode() inherited from mercuryLitCore

  // Apply theme-specific adjustments
  _applyThemeAdjustments() {
    this.updateComplete.then(() => {
      const card = this.shadowRoot.querySelector('ha-card');
      if (!card) return;

      const isDark = this.hasAttribute('dark-mode');

      if (isDark) {
        card.setAttribute('data-dark-mode', 'true');
      } else {
        card.removeAttribute('data-dark-mode');
      }
    });
  }

  render() {
    // Check configuration
    if (!this.config) {
      return this._renderConfigNeededState();
    }

    if (!this.config.entity) {
      return this._renderConfigNeededState();
    }

    // Check hass availability
    if (!this.hass) {
      return this._renderLoadingState('Waiting for Home Assistant...', '⏳');
    }

    // Check entity availability
    if (!this._isEntityAvailable()) {
      return this._renderLoadingState('Waiting for Entity...', '⏳');
    }

    const entity = this._getEntity();

    // Check if we have monthly summary data
    if (!this._hasMonthlySummaryData()) {
      return this._renderLoadingState('Loading Monthly Summary...', '📊');
    }

    // Render the main card
    return this._renderMonthlyCard(entity);
  }

  // Render loading state
  _renderLoadingState(message, icon = '⏳') {
    return html`
      <ha-card>
        <div class="loading-state">
          <div class="loading-message">${icon} ${message}</div>
          <div class="loading-description">Mercury Energy monthly data is loading</div>
        </div>
      </ha-card>
    `;
  }

  // Render configuration needed state
  _renderConfigNeededState() {
    return html`
      <ha-card>
        <div class="loading-state">
          <div class="loading-message">⚙️ Configuration Required</div>
          <div class="loading-description" style="margin-bottom: 15px;">Please configure an entity for this Mercury Energy monthly summary</div>
          <div style="font-size: 0.7em; background: var(--secondary-background-color, #f5f5f5); padding: 10px; border-radius: 4px; text-align: left;">
            <strong>Example configuration:</strong><br/>
            type: custom:mercury-monthly-summary-card<br/>
            entity: sensor.mercury_nz_energy_usage
          </div>
        </div>
      </ha-card>
    `;
  }

  _renderMonthlyCard(entity) {
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
    const projectedBill = this._extractProjectedBill(projectedBillNote);

    // Get content text from Mercury API
    const disclaimerText = attributes.content_disclaimer_text || '';
    const disclaimerParts = this._formatDisclaimerText(disclaimerText);
    const monthlyDescription = attributes.content_monthly_summary_description || 'The electricity you\'ve used in this billing period';

    // Format dates
    const startDateFormatted = this._formatDate(startDate, { day: 'numeric', month: 'short', year: 'numeric' });
    const endDateFormatted = this._formatDate(endDate, { day: 'numeric', month: 'short', year: 'numeric' });

    return html`
      <ha-card class="mercury-monthly-summary-card">
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

          ${this.config.show_progress_bar ? this._renderProgressBar(progressPercent) : ''}

          <div class="period-info flex-layout">
            <div class="period-dates">${startDateFormatted} - ${endDateFormatted}</div>
            <div class="days-remaining">${daysRemaining} days left</div>
          </div>

          ${projectedBill ? html`
            <div class="projected-bill">
              <div class="projected-content">
                <div class="plug-icon">🔌</div>
                <span>Projected electricity bill $${projectedBill.toFixed(0)}**</span>
              </div>
            </div>
          ` : ''}

          <div class="footer-notes">
            ${disclaimerParts.map(part => html`<div class="note">${part.trim()}</div>`)}
          </div>
        </div>
      </ha-card>
    `;
  }

  _renderProgressBar(progressPercent) {
    // Ensure progress is between 0 and 100
    const clampedProgress = Math.min(100, Math.max(0, progressPercent));

    return html`
      <div class="progress-container">
        <div class="progress-bar">
          <div class="progress-fill" style="width: ${clampedProgress}%;"></div>
        </div>
      </div>
    `;
  }

  getCardSize() {
    return mercuryLitCore.getCardSize(3);
  }
}

// Register the custom element
if (!customElements.get('mercury-monthly-summary-card')) {
  customElements.define('mercury-monthly-summary-card', MercuryMonthlySummaryCard);
  console.log('Mercury Monthly Summary Card: Custom element registered successfully');
} else {
  console.log('Mercury Monthly Summary Card: Custom element already registered');
}

// Add to Home Assistant custom cards registry if available
if (window.customCards) {
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: 'mercury-monthly-summary-card',
    name: 'Mercury Monthly Summary Card',
    description: 'Monthly billing summary card for Mercury Energy NZ built with LitElement',
    preview: false,
    documentationURL: 'https://github.com/bkintanar/home-assistant-mercury-co-nz'
  });
  console.log('Mercury Monthly Summary Card: Added to Home Assistant custom cards registry');
}

console.info(
  '%c MERCURY-MONTHLY-SUMMARY-CARD %c v2.0.0 ',
  'color: orange; font-weight: bold; background: black',
  'color: white; font-weight: bold; background: dimgray'
);
