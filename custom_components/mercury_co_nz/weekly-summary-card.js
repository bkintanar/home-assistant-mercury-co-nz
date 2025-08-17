// Mercury Energy Weekly Summary Card for Home Assistant
// Modern LitElement implementation of the weekly summary card

import { LitElement, html, css } from 'https://unpkg.com/lit@3.1.0/index.js?module';
import { mercuryChartStyles, mercuryColors } from './mercury-lit-styles.js';
import { mercuryLitCore } from './mercury-lit-core.js';

class MercuryWeeklySummaryCard extends LitElement {
  static styles = [
    mercuryChartStyles,
    css`
      /* Weekly-specific chart canvas ID */
      #weeklyChart {
        width: 100% !important;
        height: 100% !important;
      }
    `
  ];

  static properties = {
    hass: { type: Object },
    config: { type: Object },
    _entity: { type: Object, state: true },
    _chartLoaded: { type: Boolean, state: true },
    _selectedDataIndex: { type: Number, state: true },
    _chart: { type: Object, state: true },
    _isRendering: { type: Boolean, state: true },
    _selectedDayData: { type: Object, state: true }
  };

  constructor() {
    super();
    // Apply common core functionality using composition
    Object.assign(this, mercuryLitCore);
    this.initializeBase();

    // Weekly-specific properties
    this._selectedDataIndex = null;
    this._isRendering = false;
    this._selectedDayData = null;
    this.CHART_COLORS = { ...this.CHART_COLORS, ...mercuryColors };

    // Set up intersection observer to detect visibility changes
    this._setupVisibilityObserver();
  }

  setConfig(config) {
    this.config = this.setConfigBase(config, 'Weekly Summary');
    this.config.show_notes = config.show_notes !== false;
    console.log('Mercury Weekly Summary: Configuration set successfully with entity:', this.config.entity);
  }

  connectedCallback() {
    super.connectedCallback();
    this.setupLifecycleBase();
  }

  firstUpdated() {
    super.firstUpdated();
    // Override the hasChartData check for weekly-specific method
    this._hasChartData = this._hasWeeklySummaryData;
    this.handleFirstUpdatedBase();
  }

  updated(changedProps) {
    super.updated(changedProps);
    // Override the hasChartData check for weekly-specific method
    this._hasChartData = this._hasWeeklySummaryData;
    this.handleUpdatedBase(changedProps);

    // Weekly-specific entity update handling
    if (changedProps.has('hass') && this.hass) {
      const newEntity = this._getEntity();
      if (newEntity) {
        this._entity = newEntity;
        this._applyThemeAdjustments();
      }
    }
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this.cleanupLifecycleBase();
  }





  // Helper method to check if entity has weekly summary data
  _hasWeeklySummaryData() {
    const entity = this._getEntity();
    if (!entity || !entity.attributes) return false;

    return (
      entity.attributes.weekly_usage_cost !== undefined ||
      entity.attributes.weekly_usage_history !== undefined ||
      entity.attributes.weekly_start_date !== undefined
    );
  }

  // Helper method to format day names
  _formatDayName(dateString) {
    try {
      const date = new Date(dateString);
      return date.toLocaleDateString("en-NZ", { weekday: 'short' });
    } catch (error) {
      return '';
    }
  }

  // _formatDate() inherited from mercuryLitCore

  // Helper method to get theme colors (copied from original)
  _getThemeColor(cssVar, alpha = 1) {
    let color = '';
    const documentStyle = getComputedStyle(document.documentElement);
    color = documentStyle.getPropertyValue(cssVar).trim();

    if (!color) {
      const fallbacks = {
        '--primary-text-color': '#212121',
        '--secondary-text-color': '#727272',
        '--divider-color': '#e0e0e0'
      };
      color = fallbacks[cssVar] || '#212121';
    }

    return color;
  }

  // _isCardVisible() inherited from mercuryLitCore

  // _setupVisibilityObserver() inherited from mercuryLitCore

  // _loadChartJS() inherited from mercuryLitCore

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

  // Create or update the chart
  async _createOrUpdateChart() {
    if (!this._chartLoaded) {
      await this._loadChartJS();
    }

    await this.updateComplete;

    const entity = this._getEntity();
    if (!entity || !entity.attributes) return;

    const weeklyUsageHistory = entity.attributes.weekly_usage_history || [];
    if (!weeklyUsageHistory.length) return;

    const canvas = this.shadowRoot.getElementById('weeklyChart');
    if (!canvas) {
      console.warn('Chart canvas not found, retrying in 100ms...');
      // Retry after a short delay in case DOM is still updating
      setTimeout(() => {
        if (this.shadowRoot.getElementById('weeklyChart')) {
          this._createOrUpdateChart();
        }
      }, 100);
      return;
    }

    // Check if the card is actually visible before proceeding
    if (!this._isCardVisible()) {
      console.log('📊 Chart creation skipped - card not visible (tab switched or hidden)');
      return;
    }

    // Ensure canvas has proper dimensions
    if (canvas.offsetWidth === 0 || canvas.offsetHeight === 0) {
      // Only retry if the card is visible
      if (this._isCardVisible()) {
        console.warn('Chart canvas has no dimensions, retrying...');
        setTimeout(() => this._createOrUpdateChart(), 100);
      }
      return;
    }

    // Prepare chart data
    const labels = weeklyUsageHistory.map(day => this._formatDayName(day.date));
    const data = weeklyUsageHistory.map(day => day.consumption);

    // If chart exists, just update the data instead of recreating
    if (this._chart && this._chart.data) {
      // Update existing chart data
      this._chart.data.labels = labels;
      this._chart.data.datasets[0].data = data;
      this._chart.update('none'); // 'none' disables animations

      console.log('📊 Updated existing chart data for weekly summary');
    } else {
      // Create new chart only if one doesn't exist
      console.log('📊 Creating new chart for weekly summary');

      // Destroy existing chart just in case
      if (this._chart) {
        this._chart.destroy();
        this._chart = null;
      }

      const ctx = canvas.getContext('2d');
      this._chart = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: labels,
          datasets: [{
            label: 'kWh',
            data: data,
            backgroundColor: this.CHART_COLORS.PRIMARY_YELLOW,
            borderColor: this.CHART_COLORS.PRIMARY_YELLOW,
            borderWidth: 2,
            borderRadius: {
              topLeft: 3,
              topRight: 3,
              bottomLeft: 0,
              bottomRight: 0
            }
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: {
            duration: 0 // Disable initial animation
          },
          plugins: {
            legend: {
              display: false
            },
            tooltip: {
              enabled: false // Disable default tooltips
            }
          },
          scales: {
            x: {
              grid: {
                display: false
              },
              ticks: {
                color: this._getThemeColor('--secondary-text-color'),
                font: {
                  size: 12
                }
              }
            },
            y: {
              beginAtZero: true,
              grid: {
                color: this._getThemeColor('--divider-color', 0.3)
              },
              ticks: {
                color: this._getThemeColor('--secondary-text-color'),
                font: {
                  size: 11
                },
                callback: function(value) {
                  return value.toFixed(1);
                }
              },
              title: {
                display: true,
                text: 'kWh',
                color: this._getThemeColor('--primary-text-color'),
                align: 'end',  // Position at top
                font: {
                  size: 12,
                  weight: 600
                }
              }
            }
          },
          onClick: (event, elements) => {
            if (elements.length > 0) {
              const dataIndex = elements[0].index;
              this._selectedDataIndex = dataIndex;

              // Get the current weekly usage history data
              const entity = this._getEntity();
              if (entity && entity.attributes && entity.attributes.weekly_usage_history) {
                this._updateSelectedDayInfo(entity.attributes.weekly_usage_history[dataIndex]);
              }

              // Note: No visual selection highlighting to match custom-chart-card behavior
            }
          },
          onHover: (event, elements) => {
            event.native.target.style.cursor = elements.length > 0 ? 'pointer' : 'default';
          }
        }
      });
    }

    // Auto-select the latest day if no selection exists
    if (weeklyUsageHistory.length > 0 && this._selectedDataIndex === null) {
      this._selectedDataIndex = weeklyUsageHistory.length - 1;
      this._updateSelectedDayInfo(weeklyUsageHistory[this._selectedDataIndex]);
    }
  }

  // Update selected day info
  _updateSelectedDayInfo(dayData) {
    if (!dayData) return;

    const dateFormatted = this._formatDate(dayData.date, {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
      year: 'numeric'
    });

    // Store the selected day info and trigger a re-render
    this._selectedDayData = {
      dateFormatted,
      cost: dayData.cost,
      consumption: dayData.consumption
    };

    // Trigger LitElement re-render
    this.requestUpdate();
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

    // Check if we have weekly summary data
    if (!this._hasWeeklySummaryData()) {
      return this._renderLoadingState('Loading Weekly Summary...', '📊');
    }

    // Render the main card
    return this._renderWeeklyCard(entity);
  }

  // Render loading state
  _renderLoadingState(message, icon = '⏳') {
    return html`
      <ha-card>
        <div class="loading-state">
          <div class="loading-message">${icon} ${message}</div>
          <div class="loading-description">Mercury Energy weekly data is loading</div>
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
          <div class="loading-description" style="margin-bottom: 15px;">Please configure an entity for this Mercury Energy weekly summary</div>
          <div style="font-size: 0.7em; background: var(--secondary-background-color, #f5f5f5); padding: 10px; border-radius: 4px; text-align: left;">
            <strong>Example configuration:</strong><br/>
            type: custom:mercury-weekly-summary-card<br/>
            entity: sensor.mercury_nz_energy_usage
          </div>
        </div>
      </ha-card>
    `;
  }

  _renderWeeklyCard(entity) {
    const { attributes } = entity;

    // Extract data with fallbacks
    const weeklyCost = attributes.weekly_usage_cost || 0;
    const weeklyStartDate = attributes.weekly_start_date || '';
    const weeklyEndDate = attributes.weekly_end_date || '';
    const weeklyNotes = attributes.weekly_notes || [];
    const weeklyUsageHistory = attributes.weekly_usage_history || [];

    // Format dates
    const startDateFormatted = this._formatDate(weeklyStartDate, { day: 'numeric', month: 'short', year: 'numeric' });
    const endDateFormatted = this._formatDate(weeklyEndDate, { day: 'numeric', month: 'short', year: 'numeric' });

    // Initialize selected day data if not set and we have history data
    if (!this._selectedDayData && weeklyUsageHistory.length > 0) {
      const latestDay = weeklyUsageHistory[weeklyUsageHistory.length - 1];
      this._selectedDayData = {
        dateFormatted: this._formatDate(latestDay.date, {
          weekday: 'long',
          day: 'numeric',
          month: 'long',
          year: 'numeric'
        }),
        cost: latestDay.cost,
        consumption: latestDay.consumption
      };
    }

    return html`
      <ha-card class="mercury-weekly-summary-card">
        <div class="card-content">
          <div class="header">
            <div class="title-row">
              <h3>${this.config.name}</h3>
            </div>
            <div class="subtitle">The electricity you used Monday to Sunday</div>
          </div>

          <div class="usage-summary">
            <div class="cost-row">
              <span class="cost">$${weeklyCost.toFixed(2)}</span>
            </div>
          </div>

          <div class="period-info">
            <div class="period-dates">${startDateFormatted} - ${endDateFormatted}</div>
          </div>

          ${this.config.show_notes && weeklyNotes.length > 0 ? html`
            <div class="weekly-notes">
              ${weeklyNotes.map(note => html`<div class="note">• ${note}</div>`)}
            </div>
          ` : ''}

          <div class="chart-container">
            <canvas id="weeklyChart" width="400" height="200"></canvas>
          </div>

          <div class="chart-info">
            <div class="data-info" id="dataInfo">
              ${this._selectedDayData ? html`
                <div class="usage-details">
                  <div class="usage-date">Your usage on ${this._selectedDayData.dateFormatted}</div>
                  <div class="usage-stats">$${this._selectedDayData.cost.toFixed(2)} | ${this._selectedDayData.consumption.toFixed(2)} kWh</div>
                </div>
              ` : html`Loading...`}
            </div>
          </div>
        </div>
      </ha-card>
    `;
  }

  // Use default card size from core
  // getCardSize() inherited from mercuryLitCore
}

// Register the custom element
if (!customElements.get('mercury-weekly-summary-card')) {
  customElements.define('mercury-weekly-summary-card', MercuryWeeklySummaryCard);
  console.log('Mercury Weekly Summary Card: Custom element registered successfully');
} else {
  console.log('Mercury Weekly Summary Card: Custom element already registered');
}

// Add to Home Assistant custom cards registry if available
if (window.customCards) {
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: 'mercury-weekly-summary-card',
    name: 'Mercury Weekly Summary Card',
    description: 'Weekly summary card for Mercury Energy NZ built with LitElement',
    preview: false,
    documentationURL: 'https://github.com/bkintanar/home-assistant-mercury-co-nz'
  });
  console.log('Mercury Weekly Summary Card: Added to Home Assistant custom cards registry');
}

console.info(
  '%c MERCURY-WEEKLY-SUMMARY-CARD %c v2.0.0 ',
  'color: orange; font-weight: bold; background: black',
  'color: white; font-weight: bold; background: dimgray'
);
