// chartjs-custom-card.js
// Save to /config/www/chartjs-custom-card.js

class ChartJSCustomCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });

    // Constants to eliminate magic numbers
    this.CONSTANTS = {
      ITEMS_PER_PAGE: 12,
      FONT_SIZE_SMALL: 12,
      PADDING_STANDARD: 12,
      BORDER_RADIUS: 12,
      TOOLTIP_PADDING: '8px 12px',
      MAX_LOAD_RETRIES: 3,
      CHART_DELAY: 10,
      RETRY_DELAY: 50,
      HOURLY_LABELS: [0, 6, 12, 18],
      HOURLY_LABEL_MAP: {0: '12am', 6: '6am', 12: '12pm', 18: '6pm'}
    };

    this.currentPage = 0;
    this.itemsPerPage = this.CONSTANTS.ITEMS_PER_PAGE;
    this.chart = null;
    this.chartLoaded = false;
    this.chartLoadPromise = null;
    this.loadRetryCount = 0;
    this.maxLoadRetries = this.CONSTANTS.MAX_LOAD_RETRIES;
    this.stickyTooltip = false;
    this.selectedDate = null; // Track the currently selected date
    this.isRendering = false;
    this.currentPeriod = 'daily'; // Track current time period
    this.currentHourlyDate = new Date(); // Track current date for hourly view
    this.selectedHour = null; // Track selected hour in hourly view

    // Color constants
    this.CHART_COLORS = {
      PRIMARY_YELLOW: 'rgb(255, 240, 0)',
      TEMPERATURE_BLUE: 'rgb(105, 162, 185)'
    };
  }

  // ===== HELPER METHODS (DRY PRINCIPLE) =====

  // Extract common pagination logic to eliminate duplication
  calculatePagination(data) {
    const sortedData = data.sort((a, b) => new Date(b.date) - new Date(a.date));

    let startIndex = this.currentPage * this.itemsPerPage;
    let endIndex = (this.currentPage + 1) * this.itemsPerPage;

    // Smart pagination logic for page 1
    if (this.currentPage === 1) {
      const remainingItems = sortedData.length - this.itemsPerPage;
      if (remainingItems > 0 && remainingItems < this.itemsPerPage) {
        startIndex = remainingItems;
        endIndex = sortedData.length;
      }
    }

    return {
      sortedData,
      startIndex,
      endIndex,
      pageData: sortedData.slice(startIndex, endIndex).sort((a, b) => new Date(a.date) - new Date(b.date))
    };
  }

  // Cache DOM elements to avoid repeated queries
  get elements() {
    if (!this._elements) {
      this._elements = {
        navDate: () => this.shadowRoot.querySelector('#navDate'),
        dataInfo: () => this.shadowRoot.querySelector('.data-info'),
        chartContainer: () => this.shadowRoot.querySelector('.chart-container'),
        navigation: () => this.shadowRoot.querySelector('.navigation'),
        card: () => this.shadowRoot.querySelector('ha-card'),
        canvas: () => this.shadowRoot.querySelector('#energyChart'),
        cardHeader: () => this.shadowRoot.querySelector('.card-header h3'),
        periodButtons: () => this.shadowRoot.querySelectorAll('.period-btn')
      };
    }
    return this._elements;
  }

  // Helper method for formatting hour display (12am, 3pm, etc.)
  formatHourDisplay(hour) {
    return hour === 0 ? '12am' :
           hour < 12 ? `${hour}am` :
           hour === 12 ? '12pm' :
           `${hour - 12}pm`;
  }

  // Helper method for common date formatting patterns
  formatDate(date, options = {}) {
    const defaultOptions = {
      day: 'numeric',
      month: 'short',
      year: 'numeric'
    };
    return date.toLocaleDateString("en-NZ", { ...defaultOptions, ...options });
  }

  // Helper method for entity validation and retrieval
  getEntity() {
    if (!this._hass || !this.config.entity) return null;
    return this._hass.states[this.config.entity];
  }

  // Helper method for updating navigation date display
  updateNavigationDate() {
    const navDate = this.getNavDateElement();
    if (navDate) {
      navDate.innerHTML = this.getCurrentDateDescription().replace(/\n/g, '<br/>');
    }
  }

  // ===== DOM ELEMENT CACHING (Performance) =====

  // Cached getters for frequently accessed DOM elements
  // Use cached element getters instead of repeated queries
  getNavDateElement() {
    return this.elements.navDate();
  }

  getDataInfoElement() {
    return this.elements.dataInfo();
  }

  getChartContainerElement() {
    return this.elements.chartContainer();
  }

  getNavigationElement() {
    return this.elements.navigation();
  }

  // ===== LOGGING HELPER =====

  log(message, category = 'info') {
    const emojis = {
      info: '📊',
      date: '📅',
      nav: '🔙',
      next: '🔜',
      error: '❌',
      success: '✅'
    };
    // console.log(`${emojis[category] || '📊'} ${message}`);
  }

  // ===== HTML GENERATION HELPERS =====

  // Generate usage details HTML for data display
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

  // Generate custom legend HTML based on current period
  generateCustomLegendHTML() {
    const actualLegend = `
      <div class="legend-item">
        <div class="legend-circle"></div>
        <span class="legend-label">Actual</span>
      </div>
    `;

    const temperatureLegend = `
      <div class="legend-item">
        <div class="legend-line"></div>
        <span class="legend-label">Average Temperature</span>
      </div>
    `;

    // Only show temperature legend for daily view
    const showTemperature = this.currentPeriod === 'daily';

    return `
      <div class="custom-legend">
        ${actualLegend}
        ${showTemperature ? temperatureLegend : ''}
      </div>
    `;
  }

  // Update the legend when period changes
  updateCustomLegend() {
    const existingLegend = this.shadowRoot.querySelector('.custom-legend');
    if (existingLegend) {
      existingLegend.outerHTML = this.generateCustomLegendHTML();
    }
  }

  async setConfig(config) {
    if (!config.entity) {
      throw new Error('You need to define an entity');
    }

    this.config = {
      name: 'Chart.js Custom Card',
      chart_type: 'bar', // bar, line, area, mixed
      show_navigation: true,
      items_per_page: 12,
      // No default cost rate needed - using actual Mercury Energy costs
      ...config
    };

    this.itemsPerPage = this.config.items_per_page;

    // Load Chart.js if not already loaded and start rendering
    this.ensureChartJSAndRender();
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
            this.log('Chart.js loaded successfully', 'success');
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
    this.isRendering = true;

    try {
      // Show loading state immediately
      this.showLoadingState();

      // Wait for Chart.js to load
      await this.loadChartJS();

      // Wait a small moment to ensure everything is ready
      await new Promise(resolve => setTimeout(resolve, 100));

      // Now render
      this.render();
    } catch (error) {
      console.error('📊 Failed to load Chart.js:', error);
      this.showErrorState(error.message);
    } finally {
      this.isRendering = false;
    }
  }

  showLoadingState() {
    if (!this.shadowRoot) return;
    this.shadowRoot.innerHTML = `
      <ha-card>
        <div style="padding: 20px; text-align: center;">
          <div style="margin-bottom: 10px;">📊 Loading Chart...</div>
          <div style="font-size: 0.8em; opacity: 0.7;">Please wait while dependencies load</div>
        </div>
      </ha-card>
    `;
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

    // Only update if entity state actually changed
    if (!oldHass || !this.config) {
      this.render();
      return;
    }

    const oldEntity = oldHass.states[this.config.entity];
    const newEntity = hass.states[this.config.entity];

    // Handle entity availability changes
    const wasUnavailable = !oldEntity || oldEntity.state === 'unavailable' || oldEntity.state === 'unknown';
    const isNowAvailable = newEntity && newEntity.state !== 'unavailable' && newEntity.state !== 'unknown';

    // If entity became available after being unavailable, do a full render to restore chart
    if (wasUnavailable && isNowAvailable) {
      this.render();
      return;
    }

    // Check if entity data actually changed
    if (oldEntity && newEntity &&
        oldEntity.last_changed !== newEntity.last_changed) {
      this.updateChartData(newEntity);
    }
  }

  render() {
    if (!this.config || !this._hass) return;

    // If Chart.js is not loaded yet, wait for it
    if (!this.chartLoaded) {
      if (!this.isRendering) {
        this.ensureChartJSAndRender();
      }
      return;
    }

    const entity = this.getEntity();

    // Handle missing or unavailable entity
    if (!entity || entity.state === 'unavailable' || entity.state === 'unknown') {
      // Only show connection message if we don't have existing chart DOM
      const existingCard = this.shadowRoot.querySelector('ha-card');
      if (!existingCard) {
        this.shadowRoot.innerHTML = `
          <ha-card>
            <div style="padding: 16px; color: orange; text-align: center;">
              <div>📡 Connecting to Mercury Energy...</div>
              <div style="font-size: 0.8em; margin-top: 8px; opacity: 0.7;">
                ${!entity ? 'Entity not found' : 'Connection temporarily unavailable'}
              </div>
            </div>
          </ha-card>
        `;
      } else {
        // Entity is unavailable but we have existing chart - show status in header
        this.updateConnectionStatus(false);
      }
      return;
    }

    // Entity is available - clear any connection status
    this.updateConnectionStatus(true);

    // More robust chart existence check - detect all scenarios requiring full render
    const hasCard = !!this.shadowRoot.querySelector('ha-card');
    const hasChart = !!this.chart;
    const hasCanvas = !!this.shadowRoot.querySelector('#energyChart');
    const needsFullRender = !hasCard || !hasChart || !hasCanvas;

        if (needsFullRender) {
      this.fullRender(entity);
    } else {
      // Just update the chart data
      this.updateChartData(entity);
    }
  }

  fullRender(entity) {
    this.shadowRoot.innerHTML = `
      ${this.getStyles()}

      <ha-card>
<div class="card-header">
          <h3>${this.config.name}</h3>
        </div>

        ${this.config.show_navigation ? this.renderNavigation() : ''}

        <div class="chart-container">
          <canvas id="energyChart"></canvas>
        </div>

        ${this.generateCustomLegendHTML()}

        <div class="chart-info">
          <div class="data-info">
            ${this.getLatestDateDescription()}
          </div>
        </div>
      </ha-card>
    `;

    this.attachPeriodEventListeners();
    this.attachNavigationEventListeners();

    // Small delay to ensure DOM is fully rendered before creating chart
    setTimeout(() => {
      this.createChart(entity);
    }, 10);
  }

  updateConnectionStatus(isConnected) {
    const cardHeader = this.shadowRoot.querySelector('.card-header h3');
    if (!cardHeader) return;

    // Remove any existing connection status
    const existingStatus = cardHeader.querySelector('.connection-status');
    if (existingStatus) {
      existingStatus.remove();
    }

    if (!isConnected) {
      // Add disconnected indicator
      const statusElement = document.createElement('span');
      statusElement.className = 'connection-status';
      statusElement.innerHTML = ' <span style="color: orange; font-size: 0.8em;">📡 Reconnecting...</span>';
      cardHeader.appendChild(statusElement);
    }
  }

  updateChartData(entity) {
    // Ensure Chart.js is loaded before trying to update
    if (!this.chartLoaded || !window.Chart) {
      console.log('📊 Chart.js not ready for updateChartData, triggering load...');
      this.ensureChartJSAndRender();
      return;
    }

    if (!this.chart) {
      this.createChart(entity);
      return;
    }

    // Store current scroll position to prevent jumping
    const scrollTop = window.pageYOffset || document.documentElement.scrollTop;

    // Page info removed - no longer displayed

    const dataInfo = this.getDataInfoElement();
    if (dataInfo) {
      this.resetInfoDisplay();
    }

    // Get updated data based on current period
    let rawUsageData, rawTempData;

    if (this.currentPeriod === 'hourly') {
      rawUsageData = entity.attributes.hourly_usage_history || [];
      rawTempData = []; // No temperature data for hourly view
    } else if (this.currentPeriod === 'monthly') {
      rawUsageData = entity.attributes.monthly_usage_history || [];
      rawTempData = []; // No temperature data for monthly view
    } else {
      rawUsageData = entity.attributes.daily_usage_history || [];
      rawTempData = entity.attributes.recent_temperatures || [];
    }

    const chartData = this.processChartData(rawUsageData, rawTempData);



    // Update chart data without destroying/recreating
    this.chart.data.labels = chartData.labels;
    this.chart.data.datasets[0].data = chartData.usage;

    // Only update temperature data if the dataset exists (not for hourly view)
    if (this.chart.data.datasets[1]) {
      this.chart.data.datasets[1].data = chartData.temperature;
    }



    // Update chart theme colors in case theme changed
    this.updateChartTheme();

    // Store raw data for click events
    this.chartRawData = {
      usage: chartData.rawUsage,
      temp: chartData.rawTemp
    };

        // Animate the update (use 'none' to prevent any animation-related scrolling)
    this.chart.update('none');

    // Restore scroll position if it changed
    setTimeout(() => {
      const newScrollTop = window.pageYOffset || document.documentElement.scrollTop;
      if (newScrollTop !== scrollTop) {
        window.scrollTo(0, scrollTop);
      }
    }, 0);

    // Update navigation to reflect current page state
    this.updateNavigation();

    // Auto-select the latest data point after updating chart data
    if (chartData.usage.length > 0) {
      const latestIndex = chartData.usage.length - 1;
      this.handleChartClick(latestIndex);
    }
  }

  updateChartTheme() {
    if (!this.chart) return;

    // Update tooltip colors to match current theme
    this.chart.options.plugins.tooltip.backgroundColor = this.getThemeColor('--ha-card-background', 0.95);
    this.chart.options.plugins.tooltip.titleColor = this.getThemeColor('--primary-text-color');
    this.chart.options.plugins.tooltip.bodyColor = this.getThemeColor('--primary-text-color');
    this.chart.options.plugins.tooltip.borderColor = this.getThemeColor('--divider-color');

    // Update legend colors (only for visible items)
    this.chart.options.plugins.legend.labels.color = this.getThemeColor('--primary-text-color');

    // Update axis colors
    this.chart.options.scales.x.ticks.color = this.getThemeColor('--secondary-text-color');
    this.chart.options.scales.y.ticks.color = this.getThemeColor('--secondary-text-color');
    this.chart.options.scales.y.title.color = this.getThemeColor('--primary-text-color');
    this.chart.options.scales.y.grid.color = this.getThemeColor('--divider-color', 0.3);
  }

  createChart(entity) {
    // Double-check Chart.js is available
    if (!window.Chart) {
      console.error('📊 Chart.js not available in createChart');
      this.ensureChartJSAndRender();
      return;
    }

    try {
      // Get data based on current period
      let rawUsageData, rawTempData;

            if (this.currentPeriod === 'hourly') {
        rawUsageData = entity.attributes.hourly_usage_history || [];
        rawTempData = []; // No temperature data for hourly view

        // Set currentHourlyDate to the latest available date from the data
        if (rawUsageData.length > 0) {
          // Find the latest date in the hourly data
          const sortedData = rawUsageData.sort((a, b) => new Date(b.datetime || b.date) - new Date(a.datetime || a.date));
          const latestDataItem = sortedData[0];

          if (latestDataItem && (latestDataItem.datetime || latestDataItem.date)) {
            const latestDataDate = new Date(latestDataItem.datetime || latestDataItem.date);

            // Only update if this is the first time loading hourly or if we don't have a current date set
            if (!this.currentHourlyDate || this.currentHourlyDate > latestDataDate) {
              this.currentHourlyDate = latestDataDate;
              this.log(`Set hourly date to latest available data: ${this.currentHourlyDate.toDateString()}`, 'date');
            }
          }
        }

        // Fallback: if no data available, use today's date (but limit to reasonable past)
        if (!this.currentHourlyDate) {
          const today = new Date();
          today.setDate(today.getDate() - 1); // Default to yesterday if no data
          this.currentHourlyDate = today;
          console.log('📅 No hourly data available, defaulting to yesterday:', this.currentHourlyDate.toDateString());
        }
      } else if (this.currentPeriod === 'monthly') {
        rawUsageData = entity.attributes.monthly_usage_history || [];
        rawTempData = []; // No temperature data for monthly view
      } else {
        rawUsageData = entity.attributes.daily_usage_history || [];
        rawTempData = entity.attributes.recent_temperatures || [];
      }

      // If no fresh data available but we have cached data, use it
      if ((!rawUsageData.length || (!rawTempData.length && this.currentPeriod !== 'hourly')) && this.lastKnownData) {
        console.log('📊 Using cached data during reconnection');
        // We'll still create the chart but with a loading indicator
      }

    // Process data for current page
    const chartData = this.processChartData(rawUsageData, rawTempData);

        const canvas = this.shadowRoot.getElementById('energyChart');
    if (!canvas) {
      // Retry after a short delay if canvas not ready
      setTimeout(() => {
        this.createChart(entity);
      }, 50);
      return;
    }

    const ctx = canvas.getContext('2d');
    if (!ctx) {
      return;
    }

    // Destroy existing chart if it exists
    if (this.chart) {
      this.chart.destroy();
    }

    // Store raw data for click events
    this.chartRawData = {
      usage: chartData.rawUsage,
      temp: chartData.rawTemp
    };

    // Get chart configuration based on current period
    const chartConfig = this.getChartConfig(chartData);

    // Create new Chart.js chart
    this.chart = new Chart(ctx, chartConfig);

    // Auto-select the latest data point (last index since data is sorted oldest to newest)
    if (chartData.usage.length > 0) {
      const latestIndex = chartData.usage.length - 1;
      this.handleChartClick(latestIndex);
    }

    // Always update navigation after chart creation (especially important for hourly view)
    this.updateNavigation();

    } catch (error) {
      console.error('📊 Error creating chart:', error);
      this.showErrorState('Failed to create chart: ' + error.message);
    }
  }

  getChartConfig(chartData) {
    const baseConfig = {
      data: {
        labels: chartData.labels,
        datasets: this.getDatasets(chartData)
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: 'index',
          intersect: false,
        },
        plugins: {
          title: {
            display: false
          },
          legend: {
            display: false,
            position: 'top',
            labels: {
              color: this.getThemeColor('--primary-text-color'),
              usePointStyle: true,
              font: {
                size: 12
              },
              filter: function(legendItem, chartData) {
                // Only show Usage in legend, hide Temperature
                return legendItem.datasetIndex === 0;
              }
            }
          },
          tooltip: {
            enabled: false,  // Disable default hover tooltips
            external: (context) => {
              // Custom tooltip that only shows on click, not hover
              return this.handleCustomTooltip(context);
            }
          }
        },
        scales: {
          x: {
            grid: {
              display: false  // Hide X-axis grid lines
            },
            ticks: {
              color: this.getThemeColor('--secondary-text-color')
            }
          },
          y: {
            type: 'linear',
            display: true,
            title: {
              display: true,
              text: 'kWh',  // Simplified to just kWh since temp not in legend
              color: this.getThemeColor('--primary-text-color'),
              align: 'end',  // Position at top
              font: {
                size: 12,
                weight: 600
              }
            },
            grid: {
              color: this.getThemeColor('--divider-color', 0.3)  // Keep Y-axis grid visible
            },
            ticks: {
              color: this.getThemeColor('--secondary-text-color'),
              callback: function(value) {
                return value.toFixed(1);  // Just show numbers without units
              }
            }
          }
        },
        animation: {
          duration: 1500,
          easing: 'easeOutCubic',
          y: {
            duration: 1500,
            easing: 'easeOutCubic',
            from: (ctx) => {
              if (ctx.type === 'data' && ctx.mode === 'default') {
                const chart = ctx.chart;
                const {chartArea, scales} = chart;
                if (chartArea && scales.y) {
                  return scales.y.bottom;
                }
              }
              return 0;
            }
          }
        },
        onClick: (event, elements) => {
          if (elements.length > 0) {
            const dataIndex = elements[0].index;
            // Show custom tooltip using actual click position
            this.showTemperatureTooltip(event, dataIndex);
            // Update the info display
            this.handleChartClick(dataIndex);
          } else {
            // Click on empty area - hide tooltip but auto-select latest data point
            this.hideCustomTooltip();
            if (this.chart && this.chart.data.datasets[0].data.length > 0) {
              const latestIndex = this.chart.data.datasets[0].data.length - 1;
              this.handleChartClick(latestIndex);
            }
          }
        },
        onHover: (event, elements) => {
          // Only change cursor, no hover tooltips
          event.native.target.style.cursor = elements.length > 0 ? 'pointer' : 'default';
        }
      }
    };

    // Set chart type based on current period
    switch (this.currentPeriod) {
      case 'hourly':
        baseConfig.type = 'bar';
        // Update x-axis for hourly view to show only 4 labels
        baseConfig.options.scales.x.ticks.callback = function(value, index, values) {
          const labelsToShow = [0, 6, 12, 18]; // Hours to show: 12am, 6am, 12pm, 6pm
          const labelMap = {0: '12am', 6: '6am', 12: '12pm', 18: '6pm'};

          if (labelsToShow.includes(index)) {
            return labelMap[index];
          }
          return '';
        };
        break;
      case 'monthly':
        baseConfig.type = 'bar';
        // Keep scales for bar chart
        break;
      case 'daily':
      default:
        baseConfig.type = 'bar';
        break;
    }

    return baseConfig;
  }

  getDatasets(chartData) {
    switch (this.currentPeriod) {
      case 'hourly':
        return [
          {
            label: 'Usage (kWh)',
            data: chartData.usage,
            backgroundColor: this.CHART_COLORS.PRIMARY_YELLOW,
            borderColor: this.CHART_COLORS.PRIMARY_YELLOW,
            borderWidth: 2,
            borderRadius: {
              topLeft: 3,
              topRight: 3,
              bottomLeft: 0,
              bottomRight: 0
            },
            yAxisID: 'y'
          }
        ];
      case 'monthly':
        return [
          {
            label: 'Monthly Usage (kWh)',
            data: chartData.usage,
            backgroundColor: this.CHART_COLORS.PRIMARY_YELLOW,
            borderColor: this.CHART_COLORS.PRIMARY_YELLOW,
            borderWidth: 2,
            borderRadius: {
              topLeft: 3,
              topRight: 3,
              bottomLeft: 0,
              bottomRight: 0
            },
            maxBarThickness: 60,  // Limit bar width for better appearance
            categoryPercentage: 0.8,  // Control spacing between categories
            barPercentage: 0.9,  // Control bar width within category
            type: 'bar',
            yAxisID: 'y',
            order: 1
          }
        ];
      case 'daily':
      default:
        return [
          {
            label: 'Usage (kWh)',
            data: chartData.usage,
            backgroundColor: this.CHART_COLORS.PRIMARY_YELLOW,
            borderColor: this.CHART_COLORS.PRIMARY_YELLOW,
            borderWidth: 2,
            borderRadius: {
              topLeft: 3,
              topRight: 3,
              bottomLeft: 0,
              bottomRight: 0
            },
            type: 'bar',
            yAxisID: 'y',
            order: 2
          },
          {
            label: 'Temperature (°C)',
            data: chartData.temperature,
            backgroundColor: this.CHART_COLORS.TEMPERATURE_BLUE,
            borderColor: this.CHART_COLORS.TEMPERATURE_BLUE,
            borderWidth: 3,
            type: 'line',
            fill: false,
            tension: 0.4,
            pointRadius: 0,
            pointHoverRadius: 0,
            yAxisID: 'y',
            order: 1
          }
        ];
    }
  }

  // ===== DATA PROCESSING METHODS (Split for clarity) =====

  processChartData(usageData, tempData) {
    // Handle hourly data differently
    if (this.currentPeriod === 'hourly') {
      return this.processHourlyData(usageData);
    }

    // Handle monthly data differently
    if (this.currentPeriod === 'monthly') {
      return this.processMonthlyData(usageData);
    }

    return this.processDailyMonthlyData(usageData, tempData);
  }

  processHourlyData(usageData) {
      // Filter data for the selected date
      let filteredData = [];

      if (this.currentHourlyDate) {
        const targetDateStr = this.currentHourlyDate.toDateString();

        filteredData = usageData.filter(item => {
          const itemDate = new Date(item.datetime || item.date);
          return itemDate.toDateString() === targetDateStr;
        });

        // Sort by hour
        filteredData.sort((a, b) => {
          const hourA = new Date(a.datetime || a.date).getHours();
          const hourB = new Date(b.datetime || b.date).getHours();
          return hourA - hourB;
        });
      } else {
        // Fallback: use last 24 hours if no specific date is set
        const sortedUsageData = usageData.sort((a, b) => new Date(b.datetime || b.date) - new Date(a.datetime || a.date));
        filteredData = sortedUsageData.slice(0, 24).reverse();
      }

      // Create hour labels for 24 hours - create 24 labels regardless of data
      const labels = Array.from({length: 24}, (_, index) => {
        return `${index}:00`;
      });

      // Extract values - ensure we have exactly 24 values (one for each hour)
      const usageValues = Array.from({length: 24}, (_, hour) => {
        // Find data point for this specific hour
        const dataPoint = filteredData.find(item => {
          const itemHour = new Date(item.datetime || item.date).getHours();
          return itemHour === hour;
        });
        return dataPoint ? Number(dataPoint.consumption || dataPoint.usage || 0) : 0;
      });

      // Create rawUsage array that matches the 24-hour structure for click handling
      const rawUsageArray = Array.from({length: 24}, (_, hour) => {
        const dataPoint = filteredData.find(item => {
          const itemHour = new Date(item.datetime || item.date).getHours();
          return itemHour === hour;
        });
        return dataPoint || { hour: hour, consumption: 0, usage: 0 };
      });

      return {
        labels: labels,
        usage: usageValues,
        temperature: [], // No temperature for hourly
        rawUsage: rawUsageArray,
        rawTemp: []
      };
  }

  processMonthlyData(usageData) {

    // Use DRY pagination method
    const {pageData: sortedUsage} = this.calculatePagination(usageData);

        // Create labels formatted as "24 Jun", "24 Jul" for monthly billing dates
    const labels = sortedUsage.map(dp => {
      const date = new Date(dp.date);
      const day = date.getDate();
      const month = date.toLocaleDateString("en-NZ", { month: "short" });
      return `${day} ${month}`;
    });

    // Extract values using the data structure
    const usageValues = sortedUsage.map(dp => Number(dp.consumption));

    return {
      labels: labels,
      usage: usageValues,
      temperature: [], // No temperature for monthly
      rawUsage: sortedUsage,  // Keep raw data for popups
      rawTemp: []     // No temperature data for monthly
    };
  }

  processDailyMonthlyData(usageData, tempData) {
    // Use DRY pagination method for both usage and temperature data
    const {pageData: sortedUsage} = this.calculatePagination(usageData);
    const {pageData: sortedTemp} = this.calculatePagination(tempData);

    // Create labels from usage data (using same format as your ApexCharts)
    const labels = sortedUsage.map(dp =>
      new Date(dp.date).toLocaleDateString("en-NZ", { weekday: "short" })
    );

    // Extract values using your exact data structure
    const usageValues = sortedUsage.map(dp => Number(dp.consumption));
    const tempValues = sortedTemp.map(dp => Number(dp.temperature));



    return {
      labels: labels,
      usage: usageValues,
      temperature: tempValues,
      rawUsage: sortedUsage,  // Keep raw data for popups
      rawTemp: sortedTemp     // Keep raw data for popups
    };
  }

  handleCustomTooltip(context) {
    // This is called by Chart.js but we handle tooltips manually
    return;
  }

  showTemperatureTooltip(event, dataIndex) {
    // Remove any existing custom tooltip
    this.hideCustomTooltip();

    // Skip tooltip for hourly view (no temperature data)
    if (this.currentPeriod === 'hourly' || !this.chart.data.datasets[1]) {
      return;
    }

    // Get temperature data
    const tempValue = this.chart.data.datasets[1].data[dataIndex];

    // Get the actual pixel position of the temperature data point
    const meta = this.chart.getDatasetMeta(1); // Temperature dataset (index 1)
    const dataPoint = meta.data[dataIndex];

    // Get the exact center position of the temperature data point
    const dataPointX = dataPoint.x;
    const dataPointY = dataPoint.y;

    // Create custom tooltip element
    const tooltip = document.createElement('div');
    tooltip.className = 'custom-tooltip';
    tooltip.id = 'customTooltip';

    // Content without arrow (arrow will be separate)
    tooltip.innerHTML = `
      <span class="tooltip-text">${tempValue.toFixed(0)}°C</span>
    `;

    // Apply dynamic styling based on current theme
    const bgColor = this.getThemeColor('--ha-card-background');
    const borderColor = this.getThemeColor('--divider-color');
    const textColor = this.getThemeColor('--primary-text-color');

    tooltip.style.background = bgColor;
    tooltip.style.border = `1px solid ${borderColor}`;
    tooltip.style.color = textColor;
    tooltip.style.borderRadius = '6px';
    tooltip.style.padding = '8px 12px';
    tooltip.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.15)';
    tooltip.style.fontSize = '14px';
    tooltip.style.fontWeight = '600';
    tooltip.style.pointerEvents = 'none';
    tooltip.style.whiteSpace = 'nowrap';
    tooltip.style.position = 'absolute';
    tooltip.style.zIndex = '10000';

    // Position relative to the chart container first
    const chartContainer = this.getChartContainerElement();
    chartContainer.style.position = 'relative';

    // Add tooltip to DOM first so we can measure it
    chartContainer.appendChild(tooltip);

    // Get the canvas element and adjust for chart area offset
    const canvas = this.shadowRoot.getElementById('energyChart');
    const chartArea = this.chart.chartArea;

    // Chart.js coordinates are already positioned relative to the container
    // No adjustment needed - use raw coordinates
    const targetX = dataPointX+10;
    const targetY = dataPointY+10;


    // Get actual tooltip dimensions after it's rendered
    const tooltipWidth = tooltip.offsetWidth;
    const tooltipHeight = tooltip.offsetHeight;

    // Arrow dimensions
    const arrowWidth = 10;
    const arrowHeight = 8;

    // Position tooltip above the data point
    const tooltipLeft = targetX - (tooltipWidth / 2);
    const tooltipTop = targetY - arrowHeight - tooltipHeight;

    // Position arrow below tooltip, pointing down at the data point
    const arrowLeft = targetX - (arrowWidth / 2);
    const arrowTop = targetY - arrowHeight;

    tooltip.style.left = `${tooltipLeft}px`;
    tooltip.style.top = `${tooltipTop}px`;

    // Create the arrow
    const arrow = document.createElement('div');
    arrow.className = 'tooltip-arrow';
    arrow.id = 'customTooltipArrow';

    arrow.style.position = 'absolute';
    arrow.style.width = '0';
    arrow.style.height = '0';
    arrow.style.borderLeft = `${arrowWidth / 2}px solid transparent`;
    arrow.style.borderRight = `${arrowWidth / 2}px solid transparent`;
    arrow.style.borderTop = `${arrowHeight}px solid ${bgColor}`;
    arrow.style.zIndex = '10001';

    // Create arrow border
    const arrowBorder = document.createElement('div');
    arrowBorder.className = 'tooltip-arrow-border';
    arrowBorder.id = 'customTooltipArrowBorder';

    arrowBorder.style.position = 'absolute';
    arrowBorder.style.width = '0';
    arrowBorder.style.height = '0';
    arrowBorder.style.borderLeft = '6px solid transparent';
    arrowBorder.style.borderRight = '6px solid transparent';
    arrowBorder.style.borderTop = `9px solid ${borderColor}`;
    arrowBorder.style.zIndex = '9999';

    // Position elements
    arrow.style.left = `${arrowLeft}px`;
    arrow.style.top = `${arrowTop}px`;

    arrowBorder.style.left = `${arrowLeft - 1}px`;
    arrowBorder.style.top = `${arrowTop - 1}px`;

    // Add to container
    chartContainer.appendChild(arrowBorder);
    chartContainer.appendChild(arrow);

    // Set sticky mode
    this.stickyTooltip = true;
  }

  hideCustomTooltip() {
    // Look for all tooltip elements in chart container
    const chartContainer = this.getChartContainerElement();

    if (chartContainer) {
      // Remove main tooltip
      const tooltip = chartContainer.querySelector('#customTooltip');
      if (tooltip) tooltip.remove();

      // Remove arrow
      const arrow = chartContainer.querySelector('#customTooltipArrow');
      if (arrow) arrow.remove();

      // Remove arrow border
      const arrowBorder = chartContainer.querySelector('#customTooltipArrowBorder');
      if (arrowBorder) arrowBorder.remove();
    }

    // Fallback: look in shadow root
    const fallbackTooltip = this.shadowRoot.getElementById('customTooltip');
    if (fallbackTooltip) fallbackTooltip.remove();

    const fallbackArrow = this.shadowRoot.getElementById('customTooltipArrow');
    if (fallbackArrow) fallbackArrow.remove();

    const fallbackArrowBorder = this.shadowRoot.getElementById('customTooltipArrowBorder');
    if (fallbackArrowBorder) fallbackArrowBorder.remove();

    const fallbackDebugDot = this.shadowRoot.getElementById('debugDot');
    if (fallbackDebugDot) fallbackDebugDot.remove();

    this.stickyTooltip = false;
  }

  startStickyTooltip(elements, position) {
    // No longer needed - using custom DOM tooltip
  }

  stopStickyTooltip() {
    this.hideCustomTooltip();
    this.resetInfoDisplay();
  }

  handleChartClick(dataIndex) {
    const usageData = this.chart.data.datasets[0].data;
    const tempData = this.chart.data.datasets[1] ? this.chart.data.datasets[1].data : [];

    const usageValue = usageData[dataIndex];
    const tempValue = tempData[dataIndex] || 0;

    // Get the actual date from raw data
    let date;
    if (this.currentPeriod === 'hourly') {
      // For hourly data, create a date representing the hour
      date = new Date().toISOString(); // Use current date with the selected hour
    } else {
      const usageDate = this.chartRawData.usage[dataIndex]?.date;
      const tempDate = this.chartRawData.temp[dataIndex]?.date;
      date = usageDate || tempDate || new Date().toISOString();
    }

    // Update the info area instead of showing popup
    this.updateInfoDisplay(date, usageValue, tempValue, dataIndex);
  }

  updateInfoDisplay(date, usage, temperature, dataIndex) {
    const dataInfo = this.getDataInfoElement();
    if (!dataInfo) return;

    // Store the selected date
    this.selectedDate = date;

        // Handle hourly data differently
    if (this.currentPeriod === 'hourly') {
      const hour = dataIndex;
      this.selectedHour = hour; // Track selected hour

      const hourDisplay = this.formatHourDisplay(hour);

      const rawUsageEntry = this.chartRawData.usage[dataIndex];
      const actualCost = rawUsageEntry && rawUsageEntry.cost ? rawUsageEntry.cost : 0;

                        // Update the navigation date for hourly with proper format (short for nav)
      if (!this.currentHourlyDate) {
        return; // Don't update if date is not set yet
      }

      const navDateText = this.formatDate(this.currentHourlyDate);

      // Full date format for chart info (same as daily)
      const fullDateText = this.formatDate(this.currentHourlyDate, {
        weekday: 'long',
        month: 'long'
      });

      const navDate = this.getNavDateElement();
      if (navDate) {
        navDate.innerHTML = `${navDateText}<br/>${hourDisplay}`;
      }

      // Update the display for hourly
      dataInfo.innerHTML = this.generateUsageDetailsHTML(fullDateText, hourDisplay, actualCost, usage, true);
      return;
    }

    // Daily/Monthly data handling (existing logic)
    // Format the date for the top line (same format as getLatestDateDescription)
    const dateObj = new Date(date);
    let selectedDate = this.formatDate(dateObj);

    // Use actual cost data from Mercury API (not estimated)
    const rawUsageEntry = this.chartRawData.usage[dataIndex];
    const actualCost = rawUsageEntry && rawUsageEntry.cost ? rawUsageEntry.cost : 0;

    // For monthly periods, show billing period range in navigation
    if (this.currentPeriod === 'monthly' && rawUsageEntry && rawUsageEntry.invoiceFrom && rawUsageEntry.invoiceTo) {
      const fromDate = new Date(rawUsageEntry.invoiceFrom);
      const toDate = new Date(rawUsageEntry.invoiceTo);
      const fromFormatted = this.formatDate(fromDate, { day: 'numeric', month: 'short', year: 'numeric' });
      const toFormatted = this.formatDate(toDate, { day: 'numeric', month: 'short', year: 'numeric' });
      selectedDate = `${fromFormatted} - ${toFormatted}`;
    }

    // Format the date nicely for the detailed view
    const formattedDate = this.formatDate(dateObj, {
      weekday: 'long',
      month: 'long'
    });

    // Update the navigation date
    const navDate = this.getNavDateElement();
    if (navDate) {
      navDate.textContent = selectedDate;
    }

    // Update the display to show selected date at top and details below
    // For monthly period, show "billing period" instead of date
    const isMonthly = this.currentPeriod === 'monthly';
    dataInfo.innerHTML = this.generateUsageDetailsHTML(formattedDate, null, actualCost, usage, false, isMonthly);
  }

  resetInfoDisplay() {
    // Clear the selected date
    this.selectedDate = null;

    // Update the navigation date
    this.updateNavigationDate();

    const dataInfo = this.getDataInfoElement();
    if (dataInfo) {
      dataInfo.innerHTML = `${this.getLatestDateDescription()}`;
    }
  }

  hasPreviousPageData() {
    const entity = this.getEntity();
    if (!entity) return false;

    // For hourly view, check if there's data for the previous day
    if (this.currentPeriod === 'hourly') {
      if (!this.currentHourlyDate) {
        return false; // No navigation until date is set
      }

      const rawHourlyData = entity.attributes.hourly_usage_history || [];
      if (rawHourlyData.length === 0) {
        return false; // No hourly data available
      }

      // Get the previous day
      const previousDay = new Date(this.currentHourlyDate);
      previousDay.setDate(previousDay.getDate() - 1);
      const previousDayStr = previousDay.toDateString();

      // Check if there's any data for the previous day
      const hasDataForPreviousDay = rawHourlyData.some(item => {
        const itemDate = new Date(item.datetime || item.date);
        return itemDate.toDateString() === previousDayStr;
      });

      return hasDataForPreviousDay;
    }

    // For monthly view, check monthly data specifically
    if (this.currentPeriod === 'monthly') {
      const rawMonthlyData = entity.attributes.monthly_usage_history || [];
      const nextPageStartIndex = (this.currentPage + 1) * this.itemsPerPage;
      return rawMonthlyData.length > nextPageStartIndex;
    }

    // For daily view, check daily data
    const rawUsageData = entity.attributes.daily_usage_history || [];
    // Check if there's more data beyond the current page (older data)
    const nextPageStartIndex = (this.currentPage + 1) * this.itemsPerPage;
    return rawUsageData.length > nextPageStartIndex;
  }

  hasNextPageData() {
    // For hourly view, check if we can go to next day and if there's data available
    if (this.currentPeriod === 'hourly') {
            if (!this.currentHourlyDate) {
        return false; // No navigation until date is set
      }

      const entity = this.getEntity();
      if (!entity) return false;

      const tomorrow = new Date(this.currentHourlyDate);
      tomorrow.setDate(tomorrow.getDate() + 1);
      const today = new Date();

      // Reset time to start of day for accurate comparison
      tomorrow.setHours(0, 0, 0, 0);
      today.setHours(0, 0, 0, 0);

      // First check if tomorrow is not beyond today
      if (tomorrow > today) {
        return false; // Cannot go beyond today
      }

      // Then check if there's actual data for tomorrow
      const rawHourlyData = entity.attributes.hourly_usage_history || [];
      if (rawHourlyData.length === 0) {
        return false; // No hourly data available
      }

      const tomorrowStr = tomorrow.toDateString();

      // Check if there's any data for tomorrow
      const hasDataForTomorrow = rawHourlyData.some(item => {
        const itemDate = new Date(item.datetime || item.date);
        return itemDate.toDateString() === tomorrowStr;
      });

      return hasDataForTomorrow;
    }

    // For monthly view, check if we can go to newer data (page 0 = latest)
    if (this.currentPeriod === 'monthly') {
      return this.currentPage > 0;
    }

    // For daily view, next means newer data, only available if we're not on page 0
    return this.currentPage > 0;
  }

  updateNavigation() {
    const navContainer = this.getNavigationElement();
    if (navContainer && this.config.show_navigation) {
      navContainer.innerHTML = this.getNavigationHTML();
      this.attachNavigationEventListeners(); // Re-attach only navigation event listeners
    }
  }

  getNavigationHTML() {
    const hasNextData = this.hasNextPageData();
    const hasPrevData = this.hasPreviousPageData();
    // Always get fresh date for current page, clear any selected date first
    this.selectedDate = null;
        const dateText = this.getCurrentDateDescription();

    return `
      <div class="nav-info">
        <div class="nav-date-container">
          <div class="nav-column nav-column-left">
            <span class="nav-arrow ${hasPrevData ? '' : 'nav-arrow-hidden'}" id="prevBtn">&lt;</span>
          </div>
          <div class="nav-column nav-column-center">
            <span id="navDate">${dateText.replace(/\n/g, '<br/>')}</span>
          </div>
          <div class="nav-column nav-column-right">
            <span class="nav-arrow ${hasNextData ? '' : 'nav-arrow-hidden'}" id="nextBtn">&gt;</span>
          </div>
        </div>
      </div>
    `;
  }

  renderNavigation() {
    return `
      <div class="time-period-selector">
        <button class="period-btn" data-period="hourly">HOURLY</button>
        <button class="period-btn active" data-period="daily">DAILY</button>
        <button class="period-btn" data-period="monthly">MONTHLY</button>
      </div>
      <div class="navigation">
        ${this.getNavigationHTML()}
      </div>
    `;
  }

  getLatestDateDescription() {
    const entity = this.getEntity();
    if (!entity) return 'No data available';

    // Use appropriate data source based on current period
    let rawUsageData;
    if (this.currentPeriod === 'monthly') {
      rawUsageData = entity.attributes.monthly_usage_history || [];
    } else {
      rawUsageData = entity.attributes.daily_usage_history || [];
    }

    if (rawUsageData.length === 0) return 'No data available';

    // Get the data for current page using smart pagination
    const sortedUsageData = rawUsageData.sort((a, b) => new Date(b.date) - new Date(a.date));

        // Smart pagination logic (same as processChartData)
    let startIndex = this.currentPage * this.itemsPerPage;
    let endIndex = (this.currentPage + 1) * this.itemsPerPage;

    // If we're on page 1, check if we should show all data instead of just overflow
    if (this.currentPage === 1) {
      const remainingItems = sortedUsageData.length - this.itemsPerPage;
      // If there are fewer than a full page of remaining items, show ALL data from beginning
      if (remainingItems > 0 && remainingItems < this.itemsPerPage) {
        startIndex = remainingItems; // Start from the overflow amount to show different dates
        endIndex = sortedUsageData.length; // Show to the end
      }
    }

    const sortedUsage = sortedUsageData.slice(startIndex, endIndex);

    if (sortedUsage.length === 0) return 'No data available';

    // For monthly periods, show the billing period date range
    if (this.currentPeriod === 'monthly') {
      const latestEntry = sortedUsage[0];
      if (latestEntry.invoiceFrom && latestEntry.invoiceTo) {
        const fromDate = new Date(latestEntry.invoiceFrom);
        const toDate = new Date(latestEntry.invoiceTo);
        const fromFormatted = this.formatDate(fromDate, { day: 'numeric', month: 'short', year: 'numeric' });
        const toFormatted = this.formatDate(toDate, { day: 'numeric', month: 'short', year: 'numeric' });
        return `${fromFormatted} - ${toFormatted}`;
      }
    }

    // Get the most recent date from the current page (first item since sorted newest first)
    const latestDate = new Date(sortedUsage[0].date);
    const formattedDate = this.formatDate(latestDate);

    return formattedDate;
  }

    getCurrentDateDescription() {
    // Handle hourly view differently
    if (this.currentPeriod === 'hourly') {
      if (!this.currentHourlyDate) {
        return 'Loading...'; // Show loading while date is being determined
      }

      const dateText = this.formatDate(this.currentHourlyDate);

      if (this.selectedHour !== null) {
        const hourDisplay = this.formatHourDisplay(this.selectedHour);
        return `${dateText}\n${hourDisplay}`;
      }

      return dateText;
    }

    // Return selected date if available, otherwise return latest date
    if (this.selectedDate) {
      const dateObj = new Date(this.selectedDate);
      return this.formatDate(dateObj);
    }
    return this.getLatestDateDescription();
  }

  getPageDescription() {
    if (this.currentPage === 0) return 'Latest Data';
    return `${this.currentPage * this.itemsPerPage} days ago`;
  }

  attachNavigationEventListeners() {
    const prevBtn = this.shadowRoot.getElementById('prevBtn');
    const nextBtn = this.shadowRoot.getElementById('nextBtn');

    if (prevBtn) {
            prevBtn.addEventListener('click', () => {
        this.hideCustomTooltip(); // Hide tooltip when navigating

        if (this.currentPeriod === 'hourly') {
          // For hourly view, go to previous day
          if (this.currentHourlyDate) {
            this.currentHourlyDate.setDate(this.currentHourlyDate.getDate() - 1);
            this.selectedHour = null; // Clear selected hour
            this.log(`HOURLY PREV CLICKED - date: ${this.currentHourlyDate.toDateString()}`, 'nav');

            // For hourly view, we need to recreate the chart to filter data for the new date
            const entity = this.getEntity();
            this.createChart(entity);

            return; // Skip the general updateChartData call below
          }
        } else {
          // For daily/monthly view, use page navigation
          console.log('🔙 PREV CLICKED - before:', this.currentPage);
          this.currentPage++;
          this.selectedDate = null; // Clear selected date when changing pages
          console.log('🔙 PREV CLICKED - after:', this.currentPage);
        }

        // Get the entity and update chart data
        const entity = this.getEntity();
        this.updateChartData(entity);
      });
    }

    if (nextBtn) {
      nextBtn.addEventListener('click', () => {
        this.hideCustomTooltip(); // Hide tooltip when navigating

        if (this.currentPeriod === 'hourly') {
          // For hourly view, go to next day (but not beyond today)
          if (this.currentHourlyDate) {
            const tomorrow = new Date(this.currentHourlyDate);
            tomorrow.setDate(tomorrow.getDate() + 1);
            const today = new Date();

            // Reset time to start of day for accurate comparison (same as hasNextPageData)
            tomorrow.setHours(0, 0, 0, 0);
            today.setHours(0, 0, 0, 0);

            if (tomorrow <= today) {
              this.currentHourlyDate = tomorrow;
              this.selectedHour = null; // Clear selected hour
              this.log(`HOURLY NEXT CLICKED - date: ${this.currentHourlyDate.toDateString()}`, 'next');

              // For hourly view, we need to recreate the chart to filter data for the new date
              const entity = this.getEntity();
              this.createChart(entity);
            }
          }
        } else {
          // For daily/monthly view, use page navigation
          if (this.currentPage > 0) {
            this.currentPage--;
            this.selectedDate = null; // Clear selected date when changing pages

            // Get the entity and update chart data
            const entity = this.getEntity();
            this.updateChartData(entity);
          }
        }
      });
    }
  }

  attachPeriodEventListeners() {

    // Add event listeners for time period buttons (called only once)
    const periodButtons = this.shadowRoot.querySelectorAll('.period-btn');
    periodButtons.forEach(button => {
      button.addEventListener('click', () => {
        // Hide tooltip when switching periods
        this.hideCustomTooltip();

        // Remove active class from all buttons
        periodButtons.forEach(btn => btn.classList.remove('active'));
        // Add active class to clicked button
        button.classList.add('active');

                const period = button.dataset.period;
        this.log(`Selected period: ${period}`);

        // Update current period and reset related states
        const previousPeriod = this.currentPeriod;
        this.currentPeriod = period;

        // Reset states when switching periods
        if (period === 'hourly' && previousPeriod !== 'hourly') {
          // When switching to hourly, reset to latest available date (will be set in createChart)
          this.currentHourlyDate = null; // Will be set based on available data
          this.selectedHour = null;
          this.currentPage = 0; // Reset page navigation
          this.selectedDate = null;
        } else if (period !== 'hourly' && previousPeriod === 'hourly') {
          // When switching away from hourly, reset page navigation and hourly state
          this.currentPage = 0;
          this.selectedDate = null;
          this.selectedHour = null;
          this.currentHourlyDate = null; // Clear hourly date to prevent state leakage
        } else if (period !== previousPeriod) {
          // When switching between daily/monthly, reset navigation state
          this.currentPage = 0;
          this.selectedDate = null;
        }

        // Update legend to show/hide temperature based on current period
        this.updateCustomLegend();

        const entity = this.getEntity();
        if (entity) {
          this.createChart(entity);
          // Update navigation after chart is created to ensure latest date for new period
          this.updateNavigation();
        }
      });
    });
  }

  // Utility functions
  hexToRgba(hex, alpha = 1) {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  getThemeColor(cssVar, alpha = 1) {
    // Try to get Home Assistant theme colors from multiple sources
    let color = '';

    // Method 1: Check document root
    const documentStyle = getComputedStyle(document.documentElement);
    color = documentStyle.getPropertyValue(cssVar).trim();

    // Method 2: Check body if not found
    if (!color) {
      const bodyStyle = getComputedStyle(document.body);
      color = bodyStyle.getPropertyValue(cssVar).trim();
    }

    // Method 3: Check ha-main element (Home Assistant main container)
    if (!color) {
      const haMain = document.querySelector('ha-main') || document.querySelector('home-assistant-main');
      if (haMain) {
        const haMainStyle = getComputedStyle(haMain);
        color = haMainStyle.getPropertyValue(cssVar).trim();
      }
    }

    // Method 4: Check for theme in localStorage or detect dark mode
    const isDarkMode = this.isDarkMode();

    if (!color || color === '') {
      // Fallback colors based on dark/light mode detection
      const fallbacks = isDarkMode ? {
        // Dark mode fallbacks
        '--primary-text-color': '#e1e1e1',
        '--secondary-text-color': '#9b9b9b',
        '--divider-color': '#474747',
        '--ha-card-background': '#1c1c1c',
        '--card-background-color': '#1c1c1c'
      } : {
        // Light mode fallbacks
        '--primary-text-color': '#212121',
        '--secondary-text-color': '#727272',
        '--divider-color': '#e0e0e0',
        '--ha-card-background': '#ffffff',
        '--card-background-color': '#ffffff'
      };

      color = fallbacks[cssVar] || (isDarkMode ? '#e1e1e1' : '#212121');
    }

    // Handle different color formats
    if (color.startsWith('#')) {
      return alpha === 1 ? color : this.hexToRgba(color, alpha);
    } else if (color.startsWith('rgb')) {
      if (alpha === 1) return color;
      // Convert rgb to rgba
      const rgbMatch = color.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
      if (rgbMatch) {
        return `rgba(${rgbMatch[1]}, ${rgbMatch[2]}, ${rgbMatch[3]}, ${alpha})`;
      }
    }

    return color || (isDarkMode ? '#e1e1e1' : '#212121');
  }

  isDarkMode() {
    // Method 1: Check Home Assistant theme
    const haMain = document.querySelector('ha-main') || document.querySelector('home-assistant-main');
    if (haMain) {
      const computedStyle = getComputedStyle(haMain);
      const bgColor = computedStyle.backgroundColor;
      if (bgColor) {
        // Parse RGB values to detect if background is dark
        const rgbMatch = bgColor.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
        if (rgbMatch) {
          const r = parseInt(rgbMatch[1]);
          const g = parseInt(rgbMatch[2]);
          const b = parseInt(rgbMatch[3]);
          const brightness = (r * 299 + g * 587 + b * 114) / 1000;
          return brightness < 128; // Dark if brightness < 50%
        }
      }
    }

    // Method 2: Check document background
    const bodyBg = getComputedStyle(document.body).backgroundColor;
    if (bodyBg && bodyBg !== 'rgba(0, 0, 0, 0)') {
      const rgbMatch = bodyBg.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
      if (rgbMatch) {
        const r = parseInt(rgbMatch[1]);
        const g = parseInt(rgbMatch[2]);
        const b = parseInt(rgbMatch[3]);
        const brightness = (r * 299 + g * 587 + b * 114) / 1000;
        return brightness < 128;
      }
    }

    // Method 3: Check system preference
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
      return true;
    }

    // Method 4: Check localStorage for HA theme
    try {
      const hassData = localStorage.getItem('hassSelectedTheme');
      if (hassData) {
        const theme = JSON.parse(hassData);
        return theme && theme.includes('dark');
      }
    } catch (e) {
      // Ignore localStorage errors
    }

    // Default to light mode
    return false;
  }

  getStyles() {
    return `
      <style>
        :host {
          display: block;
        }

        ha-card {
          padding: 16px;
          background: var(--ha-card-background);
          border-radius: var(--ha-card-border-radius);
          box-shadow: var(--ha-card-box-shadow);
        }

        .card-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
        }

        .card-header h3 {
          margin: 0;
          color: var(--primary-text-color);
          font-size: 18px;
        }



        .time-period-selector {
          display: flex;
          justify-content: center;
          align-items: center;
          margin-bottom: 16px;
          background: var(--card-background-color, #f0f0f0);
          border: 1px solid var(--divider-color);
          border-radius: 12px;
          width: 100%;
        }

        .period-btn {
          flex: 1;
          background: transparent;
          border: none;
          padding: 10px 16px;
          border-radius: 8px;
          font-weight: 600;
          font-size: 13px;
          cursor: pointer;
          transition: all 0.2s ease;
          color: var(--primary-text-color);
          text-transform: uppercase;
        }

        .period-btn.active {
          background: ${this.CHART_COLORS.PRIMARY_YELLOW};
          color: #000;
          box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }

        .period-btn:hover:not(.active) {
          background: var(--primary-color);
          color: white;
        }

        .navigation {
          display: flex;
          justify-content: center;
          align-items: center;
          margin-bottom: 16px;
        }

        .nav-btn {
          display: flex;
          align-items: center;
          gap: 4px;
          background: var(--primary-color);
          color: white;
          border: none;
          padding: 8px 12px;
          border-radius: 4px;
          cursor: pointer;
          font-size: 12px;
          transition: all 0.2s;
        }

        .nav-btn:hover {
          transform: translateY(-1px);
          box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }

        .nav-info {
          font-weight: 500;
          color: var(--primary-text-color);
        }

        #navDate {
          text-align: center;
          line-height: 1.3;
          display: block;
          word-break: keep-all;
          hyphens: none;
          min-width: 0;
          padding: 0 4px;
        }

        .nav-date-container {
          display: grid;
          grid-template-columns: auto 1fr auto;
          align-items: center;
          width: 100%;
          gap: 8px;
        }

        .nav-column {
          display: flex;
          align-items: center;
        }

        .nav-column-left {
          justify-content: flex-start;
        }

        .nav-column-center {
          justify-content: center;
        }

        .nav-column-right {
          justify-content: flex-end;
        }

        .nav-arrow {
          cursor: pointer;
          color: var(--primary-color);
          font-weight: bold;
          font-size: 16px;
          padding: 4px;
          border-radius: 3px;
          transition: all 0.2s;
          user-select: none;
        }

        .nav-arrow:hover {
          background: var(--primary-color);
          color: white;
        }

        .nav-arrow-hidden {
          visibility: hidden;
          pointer-events: none;
        }

        .chart-container {
          height: 400px;
          background: var(--card-background-color, white);
          border-radius: 4px;
          padding: 10px;
          position: relative;  /* Enable relative positioning for tooltips */
        }

        .custom-legend {
          display: flex;
          justify-content: center;
          align-items: center;
          gap: 24px;
          margin: 16px 0;
        }

        .legend-item {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 16px;
        }

        .legend-circle {
          width: 12px;
          height: 12px;
          border-radius: 50%;
          background-color: ${this.CHART_COLORS.PRIMARY_YELLOW};
          border: 1px solid rgba(0, 0, 0, 0.1);
        }

        .legend-line {
          width: 24px;
          height: 2px;
          background: ${this.CHART_COLORS.TEMPERATURE_BLUE};
          border: 1px solid rgba(0, 0, 0, 0.1);
          border-radius: 1px;
        }

        .legend-label {
          font-size: 12px;
          color: var(--primary-text-color);
          font-weight: 500;
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
      </style>
    `;
  }

  getCardSize() {
    return 5;
  }

  // Add method to preserve chart state during reconnection
  preserveChartState() {
    if (this.chart && this.chart.data && this.chart.data.datasets && this.chart.data.datasets[0]) {
      this.lastKnownData = {
        labels: [...this.chart.data.labels],
        usage: [...this.chart.data.datasets[0].data],
        temperature: this.chart.data.datasets[1] ? [...this.chart.data.datasets[1].data] : []
      };
    }
  }

  // Restore chart when card reconnects to DOM (e.g., navigating back to dashboard)
  connectedCallback() {
    // Force re-render when component reconnects and chart is missing
    if (this._hass && this.config && !this.chart) {
      this.render();
    }
  }

  // Cleanup when card is removed
  disconnectedCallback() {
    // Preserve state before cleanup
    this.preserveChartState();

    // Hide custom tooltip
    this.hideCustomTooltip();

    // Destroy chart
    if (this.chart) {
      this.chart.destroy();
      this.chart = null;
    }
  }
}

// Register the card
customElements.define('mercury-energy-chart-card', ChartJSCustomCard);

// Add to Home Assistant's custom card registry
window.customCards = window.customCards || [];
window.customCards.push({
  type: 'mercury-energy-chart-card',
  name: 'Mercury Energy Chart Card',
  description: 'Professional energy usage charts for Mercury Energy NZ',
  preview: false,
  documentationURL: 'https://github.com/bkintanar/home-assistant-mercury-co-nz'
});

console.info(
  '%c MERCURY-ENERGY-CHART-CARD %c v1.0.0 ',
  'color: orange; font-weight: bold; background: black',
  'color: white; font-weight: bold; background: dimgray'
);
