// weekly-summary-card.js
// Mercury Energy Weekly Summary Card for Home Assistant

class MercuryWeeklySummaryCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });

    // Configuration tracking
    this.config = null;
    this.configSet = false;
    this.pendingConfig = null;
    this.configRetryTimeout = null;

    // Chart.js tracking
    this.chart = null;
    this.chartLoaded = false;
    this.chartLoadPromise = null;
    this.selectedDataIndex = null;
    this.loadRetryCount = 0;
    this.maxLoadRetries = 3;
    this.isRendering = false;
    this.lastKnownData = null;

    // Color constants
    this.CHART_COLORS = {
      PRIMARY_YELLOW: 'rgb(255, 240, 0)'
    };
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

  // Helper method to check if entity has weekly summary data
  hasWeeklySummaryData() {
    const entity = this.getEntity();
    if (!entity || !entity.attributes) return false;

    // Check if entity has weekly summary data
    // The actual data is in attributes, not the sensor state
    return (
      entity.attributes.weekly_usage_cost !== undefined ||
      entity.attributes.weekly_usage_history !== undefined ||
      entity.attributes.weekly_start_date !== undefined
    );
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

  // Helper method to format day names
  formatDayName(dateString) {
    try {
      const date = new Date(dateString);
      return date.toLocaleDateString("en-NZ", { weekday: 'short' });
    } catch (error) {
      return '';
    }
  }

  // Generate usage details HTML for data display (copied from custom-chart-card.js)
  generateUsageDetailsHTML(dateText, hourDisplay, cost, usage, isHourly = false, isMonthly = false) {
    let usageText;

    if (isMonthly) {
      usageText = 'Your usage this billing period';
    } else if (isHourly) {
      usageText = `Your usage at ${hourDisplay} on ${dateText}`;
    } else {
      usageText = `Your usage on ${dateText}`;
    }

    return `
      <div class="usage-details">
        <div class="usage-date">${usageText}</div>
        <div class="usage-stats">$${cost.toFixed(2)} | ${usage.toFixed(2)} kWh</div>
      </div>
    `;
  }

  async setConfig(config) {
    // Very permissive validation to prevent configuration errors
    if (!config) {
      console.warn('Mercury Weekly Summary: No config provided, using defaults...');
      config = { entity: '' }; // Provide minimal default config
    }

    if (typeof config !== 'object') {
      console.warn('Mercury Weekly Summary: Invalid config type, creating default...');
      config = { entity: config?.entity || '' }; // Try to salvage entity if possible
    }

    // Don't require entity to be set immediately - Home Assistant might be loading
    if (!config.entity) {
      console.log('Mercury Weekly Summary: No entity defined yet, will retry when available...');
      // Store the config but don't fail
      this.pendingConfig = config;

      // Set up a more patient retry mechanism
      if (!this.configRetryTimeout) {
        this.configRetryTimeout = setTimeout(() => {
          this.configRetryTimeout = null;
          if (this.pendingConfig && this.pendingConfig.entity) {
            console.log('Mercury Weekly Summary: Retrying configuration with entity:', this.pendingConfig.entity);
            this.setConfig(this.pendingConfig);
          }
        }, 5000); // Wait longer for HA to fully load
      }

      // Set a basic config so the card doesn't show "configuration error"
      this.config = {
        name: 'Weekly Summary',
        entity: '',
        show_notes: true,
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
      name: 'Weekly Summary',
      entity: config.entity,
      show_notes: true,
      ...config
    };

    this.configSet = true;
    console.log('Mercury Weekly Summary: Configuration set successfully with entity:', this.config.entity);

    // Don't immediately render - wait for hass to be available
    if (this._hass && this.isEntityAvailable()) {
      this.ensureChartJSAndRender();
    } else if (this._hass) {
      // If hass is available but entity data isn't ready, retry after a short delay
      setTimeout(() => {
        if (this.isEntityAvailable()) {
          this.ensureChartJSAndRender();
        }
      }, 1000);
    }
  }

  async loadChartJS() {
    // Check if Chart.js is already loaded
    if (window.Chart) {
      this.chartLoaded = true;
      return Promise.resolve();
    }

    // Return existing promise if already loading
    if (this.chartLoadPromise) {
      return this.chartLoadPromise;
    }

    // Load Chart.js from CDN with retry logic
    this.chartLoadPromise = new Promise((resolve, reject) => {
      const attemptLoad = (retryCount = 0) => {
        // Remove any existing failed script tags
        const existingScripts = document.querySelectorAll('script[src*="chart.umd.js"]');
        existingScripts.forEach(script => {
          if (!script.onload) script.remove();
        });

        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.5.0/dist/chart.umd.min.js';

        const cleanup = () => {
          script.onload = null;
          script.onerror = null;
        };

        script.onload = () => {
          cleanup();
          // Double check Chart.js is actually available
          if (window.Chart) {
            this.chartLoaded = true;
            this.loadRetryCount = 0;
            console.log('📊 Chart.js loaded successfully for weekly summary card');
            resolve();
          } else {
            // Chart.js script loaded but Chart object not available, retry
            console.warn('📊 Chart.js script loaded but Chart object not available, retrying...');
            if (retryCount < this.maxLoadRetries) {
              setTimeout(() => attemptLoad(retryCount + 1), 1000 * (retryCount + 1));
            } else {
              reject(new Error('Chart.js loaded but not accessible'));
            }
          }
        };

        script.onerror = () => {
          cleanup();
          console.error(`📊 Failed to load Chart.js (attempt ${retryCount + 1})`);
          if (retryCount < this.maxLoadRetries) {
            setTimeout(() => attemptLoad(retryCount + 1), 1000 * (retryCount + 1));
          } else {
            reject(new Error('Failed to load Chart.js after multiple attempts'));
          }
        };

        // Add timeout for loading
        setTimeout(() => {
          if (!this.chartLoaded) {
            cleanup();
            script.remove();
            console.error(`📊 Chart.js loading timeout (attempt ${retryCount + 1})`);
            if (retryCount < this.maxLoadRetries) {
              setTimeout(() => attemptLoad(retryCount + 1), 1000 * (retryCount + 1));
            } else {
              reject(new Error('Chart.js loading timeout'));
            }
          }
        }, 10000); // 10 second timeout

        document.head.appendChild(script);
      };

      attemptLoad();
    });

    return this.chartLoadPromise;
  }

  async ensureChartJSAndRender() {
    if (this.isRendering) return;

    // Double-check entity availability before starting render process
    if (!this.isEntityAvailable()) {
      this.showWaitingState();
      return;
    }

    this.isRendering = true;

    try {
      // Show loading state immediately
      this.showDataLoadingState();

      // Wait for Chart.js to load
      await this.loadChartJS();

      // Wait a small moment to ensure everything is ready
      await new Promise(resolve => setTimeout(resolve, 100));

      // Final check before rendering
      if (this.isEntityAvailable()) {
        this.render();
      } else {
        this.showWaitingState();
      }
    } catch (error) {
      console.error('📊 Failed to load Chart.js for weekly summary:', error);
      this.showErrorState(error.message);
    } finally {
      this.isRendering = false;
    }
  }

  showErrorState(message) {
    if (!this.shadowRoot) return;
    this.shadowRoot.innerHTML = `
      <ha-card>
        <div style="padding: 20px; text-align: center; color: #ff6b6b;">
          <div style="margin-bottom: 10px;">⚠️ Chart Load Error</div>
          <div style="font-size: 0.8em; margin-bottom: 10px;">${message}</div>
          <button onclick="location.reload()" style="background: #ff6b6b; color: white; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer;">
            Refresh Page
          </button>
        </div>
      </ha-card>
    `;
  }

  set hass(hass) {
    const oldHass = this._hass;
    this._hass = hass;

    // If we have a pending config due to hard refresh, try to apply it now
    if (!this.config && this.pendingConfig && hass) {
      console.log('Mercury Weekly Summary: Attempting to apply pending configuration with hass available');
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
        this.hasWeeklySummaryData()) {
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

    // If entity is available but doesn't have weekly summary data yet, show loading
    if (!this.hasWeeklySummaryData()) {
      this.showDataLoadingState();
      return;
    }

    // If Chart.js is not loaded yet, wait for it
    if (!this.chartLoaded) {
      if (!this.isRendering) {
        this.ensureChartJSAndRender();
      }
      return;
    }

    // Load Chart.js and render the card
    this.loadChartJS().then(() => {
      this.renderCard(entity);
      this.applyThemeAdjustments();
    }).catch(error => {
      console.error('Failed to load Chart.js for weekly summary:', error);
      this.renderCard(entity); // Render without chart as fallback
      this.applyThemeAdjustments();
    });
  }

  renderCard(entity) {
    const { attributes } = entity;

    // Extract data with fallbacks
    const weeklyCost = attributes.weekly_usage_cost || 0;
    const weeklyStartDate = attributes.weekly_start_date || '';
    const weeklyEndDate = attributes.weekly_end_date || '';
    const weeklyNotes = attributes.weekly_notes || [];
    const weeklyUsageHistory = attributes.weekly_usage_history || [];

    // Format dates
    const startDateFormatted = this.formatDate(weeklyStartDate, { day: 'numeric', month: 'short', year: 'numeric' });
    const endDateFormatted = this.formatDate(weeklyEndDate, { day: 'numeric', month: 'short', year: 'numeric' });

    // Get the latest day info for default display
    const latestDay = weeklyUsageHistory.length > 0 ? weeklyUsageHistory[weeklyUsageHistory.length - 1] : null;
    const latestDayFormatted = latestDay ? this.formatDate(latestDay.date, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }) : '';

    this.shadowRoot.innerHTML = `
      ${this.getStyles()}

      <ha-card>
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

          ${this.config.show_notes && weeklyNotes.length > 0 ? `
            <div class="weekly-notes">
              ${weeklyNotes.map(note => `<div class="note">• ${note}</div>`).join('')}
            </div>
          ` : ''}

          <div class="chart-container">
            <canvas id="weeklyChart" width="400" height="200"></canvas>
          </div>

          <div class="chart-info">
            <div class="data-info" id="dataInfo">
              ${latestDay ? this.generateUsageDetailsHTML(latestDayFormatted, null, latestDay.cost, latestDay.consumption, false, false) : 'Loading...'}
            </div>
          </div>
        </div>
      </ha-card>
    `;

    // Create chart after DOM is ready
    setTimeout(() => {
      this.createChart(weeklyUsageHistory);
      // Auto-select the latest day
      if (weeklyUsageHistory.length > 0) {
        this.selectedDataIndex = weeklyUsageHistory.length - 1;
        this.updateSelectedDayInfo(weeklyUsageHistory[this.selectedDataIndex]);
      }
    }, 100);
  }

  createChart(usageData) {
    // Double-check Chart.js is available
    if (!this.chartLoaded || !window.Chart) {
      console.error('📊 Chart.js not available in createChart for weekly summary');
      this.ensureChartJSAndRender();
      return;
    }

    try {
      // If no fresh data available but we have cached data, use it
      if (!usageData.length && this.lastKnownData) {
        console.log('📊 Using cached data during reconnection for weekly summary');
        // We'll still create the chart but with a loading indicator
      }

    const canvas = this.shadowRoot.getElementById('weeklyChart');
    if (!canvas) {
      // Retry after a short delay if canvas not ready
      setTimeout(() => {
        this.createChart(usageData);
      }, 50);
      return;
    }

    const ctx = canvas.getContext('2d');
    if (!ctx) {
      console.warn('Could not get canvas context');
      return;
    }

    // Destroy existing chart if it exists
    if (this.chart) {
      this.chart.destroy();
    }

    // Prepare chart data
    const labels = usageData.map(day => this.formatDayName(day.date));
    const consumptionData = usageData.map(day => day.consumption);

    // Create the chart
    this.chart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: 'kWh',
          data: consumptionData,
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
        plugins: {
          legend: {
            display: false
          },
          tooltip: {
            enabled: false // Disable default tooltips, we'll handle clicks manually
          }
        },
        scales: {
          x: {
            grid: {
              display: false
            },
            ticks: {
              color: this.getThemeColor('--secondary-text-color'),
              font: {
                size: 12
              }
            }
          },
          y: {
            beginAtZero: true,
            grid: {
              color: this.getThemeColor('--divider-color', 0.3)
            },
            ticks: {
              color: this.getThemeColor('--secondary-text-color'),
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
              color: this.getThemeColor('--primary-text-color'),
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
            this.selectedDataIndex = dataIndex;
            this.updateSelectedDayInfo(usageData[dataIndex]);

            // Note: No visual selection highlighting to match custom-chart-card behavior
          }
        },
        onHover: (event, elements) => {
          event.native.target.style.cursor = elements.length > 0 ? 'pointer' : 'default';
        }
      }
    });

    // Store raw data for later use (chart state preservation)
    this.chartRawData = {
      usage: usageData
    };

    } catch (error) {
      console.error('📊 Error creating chart for weekly summary:', error);
      this.showErrorState('Failed to create chart: ' + error.message);
    }
  }



  updateSelectedDayInfo(dayData) {
    const dataInfo = this.shadowRoot.getElementById('dataInfo');
    if (!dataInfo || !dayData) return;

    const formattedDate = this.formatDate(dayData.date, {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
      year: 'numeric'
    });

    // Use the same generateUsageDetailsHTML method as custom-chart-card.js
    dataInfo.innerHTML = this.generateUsageDetailsHTML(formattedDate, null, dayData.cost, dayData.consumption, false, false);
  }

  getThemeColor(cssVar, alpha = 1) {
    // Try to get Home Assistant theme colors
    let color = '';

    const documentStyle = getComputedStyle(document.documentElement);
    color = documentStyle.getPropertyValue(cssVar).trim();

    if (!color) {
      const bodyStyle = getComputedStyle(document.body);
      color = bodyStyle.getPropertyValue(cssVar).trim();
    }

    // Fallback colors based on dark/light mode detection
    const isDarkMode = this.isDarkMode();

    if (!color || color === '') {
      const fallbacks = isDarkMode ? {
        '--primary-text-color': '#e1e1e1',
        '--secondary-text-color': '#9b9b9b',
        '--divider-color': '#474747'
      } : {
        '--primary-text-color': '#212121',
        '--secondary-text-color': '#727272',
        '--divider-color': '#e0e0e0'
      };

      color = fallbacks[cssVar] || (isDarkMode ? '#e1e1e1' : '#212121');
    }

    // Handle alpha
    if (alpha === 1) return color;

    // Convert to rgba if alpha is specified
    if (color.startsWith('#')) {
      const r = parseInt(color.slice(1, 3), 16);
      const g = parseInt(color.slice(3, 5), 16);
      const b = parseInt(color.slice(5, 7), 16);
      return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }

    return color;
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
          <div style="margin-bottom: 10px;">📊 Loading Weekly Summary...</div>
          <div style="font-size: 0.8em; opacity: 0.7;">Mercury Energy weekly data is being fetched</div>
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
          <div style="font-size: 0.8em; opacity: 0.7;">Setting up Mercury Energy weekly summary configuration</div>
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
          <div style="font-size: 0.8em; opacity: 0.7; margin-bottom: 15px;">Please configure an entity for this Mercury Energy weekly summary</div>
          <div style="font-size: 0.7em; background: var(--secondary-background-color, #f5f5f5); padding: 10px; border-radius: 4px; text-align: left;">
            <strong>Example configuration:</strong><br/>
            type: custom:mercury-weekly-summary-card<br/>
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

        .subtitle {
          color: var(--secondary-text-color);
          font-size: 14px;
          margin: 0;
          line-height: 1.3;
        }

        .usage-summary {
          margin-bottom: 16px;
        }

        .cost-row {
          margin-bottom: 8px;
        }

        .cost {
          font-size: 48px;
          font-weight: 700;
          color: var(--primary-text-color);
          line-height: 1;
        }

        .period-info {
          margin-bottom: 16px;
          font-size: 14px;
        }

        .period-dates {
          color: var(--primary-text-color);
          font-weight: 500;
        }

        .weekly-notes {
          margin-bottom: 20px;
          padding: 12px;
          background: var(--card-background-color, var(--ha-card-background, #fafafa));
          border: 1px solid var(--divider-color);
          border-radius: 8px;
        }

        .note {
          color: var(--primary-text-color);
          font-size: 14px;
          margin-bottom: 4px;
          line-height: 1.4;
        }

        .note:last-child {
          margin-bottom: 0;
        }

        /* Dark mode specific styling for notes */
        ha-card[data-dark-mode="true"] .weekly-notes,
        ha-card[data-theme*="dark"] .weekly-notes,
        :host([dark-mode]) .weekly-notes {
          background: var(--card-background-color, #1e1e1e);
          border: 1px solid var(--divider-color, #3d3d3d);
        }

        .chart-container {
          height: 200px;
          margin-bottom: 20px;
          background: var(--card-background-color, white);
          border-radius: 8px;
          padding: 16px;
          border: 1px solid var(--divider-color);
        }

        /* Dark mode chart container */
        ha-card[data-dark-mode="true"] .chart-container,
        ha-card[data-theme*="dark"] .chart-container,
        :host([dark-mode]) .chart-container {
          background: var(--card-background-color, #1e1e1e);
          border: 1px solid var(--divider-color, #3d3d3d);
        }

        .chart-info {
          text-align: left;
          margin-top: 12px;
          padding: 12px;
          background: ${this.CHART_COLORS.PRIMARY_YELLOW};
          border-radius: 8px;
          border: 1px solid var(--divider-color);
          min-height: 48px;
          display: flex;
          align-items: center;
          justify-content: flex-start;
        }

        .usage-details {
          text-align: left;
        }

        .data-info {
          font-size: 14px;
          color: black;
        }

        .usage-date {
          font-size: 14px;
          color: black;
        }

        .usage-stats {
          font-size: 14px;
          color: black;
        }

        /* Responsive design */
        @media (max-width: 480px) {
          .card-content {
            padding: 16px;
          }

          .cost {
            font-size: 36px;
          }

          .chart-container {
            height: 160px;
            padding: 12px;
          }
        }
      </style>
    `;
  }

  getCardSize() {
    return 4;
  }

  // Add method to preserve chart state during reconnection
  preserveChartState() {
    if (this.chart && this.chart.data && this.chart.data.datasets && this.chart.data.datasets[0]) {
      this.lastKnownData = {
        labels: [...this.chart.data.labels],
        usage: [...this.chart.data.datasets[0].data],
        rawUsage: this.chartRawData ? [...this.chartRawData.usage] : []
      };
    }
  }

  // Restore chart when card reconnects to DOM (e.g., navigating back to dashboard)
  connectedCallback() {
    // Force re-render when component reconnects and chart is missing
    if (this._hass && this.config && this.configSet && !this.chart && this.isEntityAvailable()) {
      this.render();
    }
  }

  // Cleanup when card is removed
  disconnectedCallback() {
    // Clear any pending configuration retries
    if (this.configRetryTimeout) {
      clearTimeout(this.configRetryTimeout);
      this.configRetryTimeout = null;
    }

    // Preserve state before cleanup
    this.preserveChartState();

    // Destroy chart
    if (this.chart) {
      this.chart.destroy();
      this.chart = null;
    }
  }
}

// Register the card (prevent re-registration during hard refresh)
if (!customElements.get('mercury-weekly-summary-card')) {
  customElements.define('mercury-weekly-summary-card', MercuryWeeklySummaryCard);
  console.log('Mercury Weekly Summary Card: Custom element registered successfully');
} else {
  console.log('Mercury Weekly Summary Card: Custom element already registered');
}

// Add to Home Assistant's custom card registry
window.customCards = window.customCards || [];

// Prevent duplicate entries in customCards array
const existingCard = window.customCards.find(card => card.type === 'mercury-weekly-summary-card');
if (!existingCard) {
  window.customCards.push({
    type: 'mercury-weekly-summary-card',
    name: 'Mercury Weekly Summary Card',
    description: 'Weekly usage summary card for Mercury Energy NZ',
    preview: false,
    documentationURL: 'https://github.com/bkintanar/home-assistant-mercury-co-nz'
  });
  console.log('Mercury Weekly Summary Card: Added to Home Assistant custom cards registry');
}

console.info(
  '%c MERCURY-WEEKLY-SUMMARY-CARD %c v1.0.0 ',
  'color: orange; font-weight: bold; background: black',
  'color: white; font-weight: bold; background: dimgray'
);
