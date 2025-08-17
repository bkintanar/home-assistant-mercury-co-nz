// Mercury Energy Usage Chart Card for Home Assistant (LitElement)
// Modern LitElement implementation of the energy usage chart card with Chart.js integration

import { LitElement, html, css } from 'https://unpkg.com/lit@3.1.0/index.js?module';
import { mercuryChartStyles, mercuryColors } from './mercury-lit-styles.js';
import { mercuryLitCore } from './mercury-lit-core.js';

class MercuryEnergyUsageCard extends LitElement {
  static styles = [
    mercuryChartStyles,
    css`
      /* Energy chart specific overrides */
    `
  ];

  static properties = {
    hass: { type: Object },
    config: { type: Object },
    _entity: { type: Object, state: true },
    _chartLoaded: { type: Boolean, state: true },
    _chart: { type: Object, state: true },
    _currentPeriod: { type: String, state: true },
    _currentPage: { type: Number, state: true },
    _selectedDate: { type: Object, state: true },
    _currentHourlyDate: { type: Object, state: true },
    _selectedHour: { type: Number, state: true }
  };

  constructor() {
    super();
    // Apply common core functionality using composition
    Object.assign(this, mercuryLitCore);
    this.initializeBase();

    // Energy card-specific properties
    this._currentPeriod = 'daily';
    this._currentPage = 0;
    this._selectedDate = null;
    this._currentHourlyDate = null; // Will be set based on available data when switching to hourly
    this._selectedHour = null;
    this.itemsPerPage = 12;
    this.allowedPeriods = ['hourly', 'daily', 'monthly'];

    // Chart colors (merge with core colors)
    this.CHART_COLORS = {
      ...this.CHART_COLORS,
      PRIMARY_YELLOW: 'rgb(255, 240, 0)',
      TEMPERATURE_BLUE: 'rgb(105, 162, 185)',
      ...mercuryColors
    };

    // Set up intersection observer to detect visibility changes
    this._setupVisibilityObserver();
  }

  setConfig(config) {
    this.config = this.setConfigBase(config, 'Energy Usage');
    // Energy card-specific config defaults
    this.config = {
      chart_type: 'bar',
      show_navigation: true,
      items_per_page: 12,
      period: 'hourly|daily|monthly',
      ...this.config
    };

    // Parse allowed periods from config
    this.allowedPeriods = this.config.period
      .split('|')
      .map(p => p.trim().toLowerCase())
      .filter(p => ['hourly', 'daily', 'monthly'].includes(p));

    // If no valid periods specified, default to all
    if (this.allowedPeriods.length === 0) {
      this.allowedPeriods = ['hourly', 'daily', 'monthly'];
    }

    // Set default period to first allowed period
    if (this.allowedPeriods.includes('daily')) {
      this._currentPeriod = 'daily';
    } else {
      this._currentPeriod = this.allowedPeriods[0];
    }

    this.itemsPerPage = this.config.items_per_page;
  }

  connectedCallback() {
    super.connectedCallback();
    this.setupLifecycleBase();
  }

  firstUpdated() {
    super.firstUpdated();
    // Override the hasChartData check for energy-specific method
    this._hasChartData = this._hasChartData.bind(this);
    this.handleFirstUpdatedBase();
  }

  updated(changedProps) {
    super.updated(changedProps);
    this.handleUpdatedBase(changedProps);

    // Energy card-specific entity update handling
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
    // Hide tooltip before cleanup
    this._hideCustomTooltip();
    this.cleanupLifecycleBase();
  }

  // _getEntity() inherited from mercuryLitCore

  // _isEntityAvailable() inherited from mercuryLitCore

  // Helper method to check if entity has chart data
  _hasChartData() {
    const entity = this._getEntity();
    if (!entity || !entity.attributes) return false;

    return (
      entity.attributes.daily_usage_history ||
      entity.attributes.extended_daily_usage_history ||
      entity.attributes.hourly_usage_history ||
      entity.attributes.extended_hourly_usage_history ||
      entity.attributes.monthly_usage_history
    );
  }

  // Helper method for date formatting
  _formatDate(date, options = {}) {
    const defaultOptions = {
      day: 'numeric',
      month: 'short',
      year: 'numeric'
    };
    return date.toLocaleDateString("en-NZ", { ...defaultOptions, ...options });
  }

  // Helper method for hour formatting
  _formatHourDisplay(hour) {
    return hour === 0 ? '12am' :
           hour < 12 ? `${hour}am` :
           hour === 12 ? '12pm' :
           `${hour - 12}pm`;
  }

  // Show temperature tooltip (matches original showTemperatureTooltip)
  _showTemperatureTooltip(event, dataIndex) {
    // Remove any existing custom tooltip
    this._hideCustomTooltip();

    // Skip tooltip for hourly view (no temperature data)
    if (this._currentPeriod === 'hourly' || !this._chart?.data?.datasets?.[1]) {
      return;
    }

    // Get temperature data
    const tempValue = this._chart.data.datasets[1].data[dataIndex];

    // Get the actual pixel position of the temperature data point
    const meta = this._chart.getDatasetMeta(1); // Temperature dataset (index 1)
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
    const bgColor = this._getThemeColor('--ha-card-background');
    const borderColor = this._getThemeColor('--divider-color');
    const textColor = this._getThemeColor('--primary-text-color');

    tooltip.style.background = bgColor;
    tooltip.style.border = `1px solid ${borderColor}`;
    tooltip.style.color = textColor;
    tooltip.style.borderRadius = '6px';
    tooltip.style.padding = '8px 12px';
    tooltip.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.15)';
    tooltip.style.fontSize = '14px';
    tooltip.style.fontWeight = '600';
    tooltip.style.position = 'absolute';
    tooltip.style.zIndex = '10000';
    tooltip.style.pointerEvents = 'none';
    tooltip.style.whiteSpace = 'nowrap';

    // Get chart container
    const chartContainer = this.shadowRoot.querySelector('.chart-container');
    if (!chartContainer) return;

    const chartRect = chartContainer.getBoundingClientRect();
    const containerRect = chartContainer.getBoundingClientRect();

        // Calculate tooltip position relative to chart container
    const tooltipWidth = 60; // Estimated width
    const tooltipHeight = 32; // Estimated height
    const offset = 10; // Distance from data point

    // Position tooltip above the data point (matches original)
    let tooltipLeft = dataPointX - (tooltipWidth / 2);
    let tooltipTop = dataPointY - tooltipHeight - offset;

    // Ensure tooltip stays within chart bounds
    if (tooltipLeft < 0) tooltipLeft = 5;
    if (tooltipLeft + tooltipWidth > chartContainer.clientWidth) {
      tooltipLeft = chartContainer.clientWidth - tooltipWidth - 5;
    }
    if (tooltipTop < 0) {
      tooltipTop = dataPointY + offset;
    }

    tooltip.style.left = `${tooltipLeft}px`;
    tooltip.style.top = `${tooltipTop}px`;

    // Add tooltip to chart container
    chartContainer.appendChild(tooltip);

    // Create the arrow pointing down (matches original)
    const arrow = document.createElement('div');
    arrow.className = 'tooltip-arrow';
    arrow.id = 'customTooltipArrow';

    const arrowWidth = 10;
    const arrowHeight = 8;
    const arrowLeft = tooltipLeft + (tooltipWidth / 2) - (arrowWidth / 2);
    const arrowTop = tooltipTop + tooltipHeight; // Arrow below tooltip pointing down

    arrow.style.position = 'absolute';
    arrow.style.width = '0';
    arrow.style.height = '0';
    arrow.style.borderLeft = `${arrowWidth / 2}px solid transparent`;
    arrow.style.borderRight = `${arrowWidth / 2}px solid transparent`;
    arrow.style.borderTop = `${arrowHeight}px solid ${bgColor}`; // Point down
    arrow.style.zIndex = '10001';
    arrow.style.left = `${arrowLeft}px`;
    arrow.style.top = `${arrowTop}px`;

    // Create arrow border pointing down
    const arrowBorder = document.createElement('div');
    arrowBorder.className = 'tooltip-arrow-border';
    arrowBorder.id = 'customTooltipArrowBorder';

    arrowBorder.style.position = 'absolute';
    arrowBorder.style.width = '0';
    arrowBorder.style.height = '0';
    arrowBorder.style.borderLeft = '6px solid transparent';
    arrowBorder.style.borderRight = '6px solid transparent';
    arrowBorder.style.borderTop = `9px solid ${borderColor}`; // Point down
    arrowBorder.style.zIndex = '9999';
    arrowBorder.style.left = `${arrowLeft - 1}px`;
    arrowBorder.style.top = `${arrowTop - 1}px`;

    // Add arrows to chart container
    chartContainer.appendChild(arrowBorder);
    chartContainer.appendChild(arrow);

    // Set sticky mode
    this._stickyTooltip = true;
  }

    // Hide custom tooltip (matches original hideCustomTooltip)
  _hideCustomTooltip() {
    const chartContainer = this.shadowRoot.querySelector('.chart-container');

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

    this._stickyTooltip = false;
  }



    // Set up component when it connects
  connectedCallback() {
    super.connectedCallback();

    // Trigger chart creation if needed
    if (this._isCardVisible() && this._hasChartData() && !this._chart) {
      setTimeout(() => this._createOrUpdateChart(), 100);
    }
  }

  // Called after the element's DOM has been updated for the first time
  firstUpdated() {
    // Initialize chart on first render with small delay to ensure DOM is ready
      setTimeout(() => {
      if (this._hasChartData()) {
        // Load Chart.js if not already loaded, then create chart
        if (!this._chartLoaded) {
          this._loadChartJS().then(() => {
            if (this._isCardVisible() && !this._chart) {
              this._createOrUpdateChart();
            }
          }).catch(error => {
            console.error('📊 Failed to load Chart.js in firstUpdated:', error);
          });
        } else if (this._isCardVisible() && !this._chart) {
          this._createOrUpdateChart();
        }
      }
    }, 100);
  }

  // Called after every update
  updated(changedProperties) {
    // If hass or config changed, potentially update chart
    if (changedProperties.has('hass') || changedProperties.has('config')) {
      // Ensure Chart.js is loaded before creating chart
      if (this._isCardVisible() && this._hasChartData() && !this._chart) {
        if (!this._chartLoaded) {
          this._loadChartJS().then(() => {
            if (this._isCardVisible() && this._hasChartData() && !this._chart) {
              this._createOrUpdateChart();
            }
          }).catch(error => {
            console.error('📊 Failed to load Chart.js in updated:', error);
          });
          } else {
          this._createOrUpdateChart();
        }
      } else if (this._chart && this._hasChartData()) {
        this._updateChartData();
      }
    }
  }

  // Clean up when component disconnects
  disconnectedCallback() {
    super.disconnectedCallback();

    // Hide tooltip
    this._hideCustomTooltip();

    // Destroy chart
    if (this._chart) {
      this._chart.destroy();
      this._chart = null;
    }
  }

  // Process hourly data (matches original processHourlyData)
  _processHourlyData(usageData) {
    // Always filter data for the selected date - no fallback logic needed since currentHourlyDate is set before processing
    let filteredData = [];

    if (this._currentHourlyDate) {
      const targetDateStr = this._currentHourlyDate.toDateString();

      // Filter to only include data from the selected date
      filteredData = usageData.filter(item => {
        const itemDate = new Date(item.datetime || item.date);
        return itemDate.toDateString() === targetDateStr;
      }).sort((a, b) => {
        const hourA = new Date(a.datetime || a.date).getHours();
        const hourB = new Date(b.datetime || b.date).getHours();
        return hourA - hourB;
      });
    } else {
      console.warn('⚠️ No currentHourlyDate set for hourly processing');
    }

    // Create hour labels for 24 hours - but only show every 6th one (4 total: 0, 6, 12, 18)
    const labels = Array.from({length: 24}, (_, index) => {
      // Only show labels for hours 0, 6, 12, 18 (every 6th hour)
      if (index % 6 === 0) {
        return this._formatHourDisplay(index); // Show 12am, 6am, 12pm, 6pm
      }
      return ''; // Empty string for hidden labels
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
      return dataPoint || { hour: hour, consumption: 0, usage: 0, cost: 0 };
    });

    return {
      labels: labels,
      usage: usageValues,
      temperature: [], // No temperature for hourly
      rawUsage: rawUsageArray
    };
  }

  // Build chart datasets based on period (matches original)
  _buildChartDatasets(usageData, temperatureData) {
    switch (this._currentPeriod) {
      case 'hourly':
        return [
          {
            label: 'Hourly Usage (kWh)',
            data: usageData,
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
            data: usageData,
            backgroundColor: this.CHART_COLORS.PRIMARY_YELLOW,
            borderColor: this.CHART_COLORS.PRIMARY_YELLOW,
            borderWidth: 2,
            borderRadius: {
              topLeft: 3,
              topRight: 3,
              bottomLeft: 0,
              bottomRight: 0
            },
            barPercentage: 0.9,
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
            data: usageData,
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
            data: temperatureData,
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



  // Get raw data based on current period
  _getRawDataForPeriod(entity) {
    if (this._currentPeriod === 'hourly') {
      return entity.attributes.hourly_usage_history || [];
    } else if (this._currentPeriod === 'monthly') {
      return entity.attributes.monthly_usage_history || [];
    } else {
      // Daily
      return entity.attributes.daily_usage_history || entity.attributes.extended_daily_usage_history || [];
    }
  }

  // Get paginated data for the current page
  _getPaginatedData(rawData) {
    if (!rawData.length) return { sortedData: [], pageData: [], startIndex: 0, endIndex: 0 };

    // Sort data by date (newest first for pagination)
    const sortedData = [...rawData].sort((a, b) => new Date(b.date || b.datetime) - new Date(a.date || a.datetime));

    if (this._currentPeriod === 'hourly') {
      // For hourly, filter by current date
      const targetDate = this._currentHourlyDate.toISOString().split('T')[0];
      const dayData = sortedData.filter(item => {
        const itemDate = new Date(item.datetime || item.date).toISOString().split('T')[0];
        return itemDate === targetDate;
      });
      return { sortedData, pageData: dayData.sort((a, b) => new Date(a.datetime || a.date) - new Date(b.datetime || b.date)), startIndex: 0, endIndex: dayData.length };
    }

    // For daily/monthly, use smart pagination to always show 12 items
    let startIndex = this._currentPage * this.itemsPerPage;
    let endIndex = Math.min(startIndex + this.itemsPerPage, sortedData.length);

    // Smart pagination logic: if we're on the last page and it has fewer than 12 items,
    // adjust the start index to ensure we always show exactly 12 items (if available)
    const maxPage = Math.ceil(sortedData.length / this.itemsPerPage) - 1;
    if (this._currentPage === maxPage && sortedData.length >= this.itemsPerPage) {
      const remainingItems = sortedData.length - (this._currentPage * this.itemsPerPage);
      if (remainingItems < this.itemsPerPage) {
        // Adjust to show exactly 12 items by moving the start index back
        endIndex = sortedData.length;
        startIndex = Math.max(0, endIndex - this.itemsPerPage);
      }
    }



    const pageData = sortedData.slice(startIndex, endIndex).sort((a, b) => new Date(a.date || a.datetime) - new Date(b.date || b.datetime));

    return { sortedData, pageData, startIndex, endIndex };
  }

  // Check if navigation should be visible
  _shouldShowNavigation(rawData) {
    // Always show navigation for consistency with original card - arrows will be hidden when not needed
    return rawData.length > 0;
  }

  // Setup intersection observer for visibility detection
  _setupVisibilityObserver() {
    if ('IntersectionObserver' in window) {
      this._visibilityObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
          if (entry.isIntersecting && entry.target === this) {
            setTimeout(() => {
              if (this._isCardVisible() && this._chartLoaded && this._hasChartData() && !this._chart) {
              this._createOrUpdateChart();
              }
            }, 100);
          }
        });
      }, {
        root: null,
        rootMargin: '50px',
        threshold: 0.1
      });
    }

    // Also listen for visibility change events (tab switching)
    if (typeof document !== 'undefined') {
      this._handleVisibilityChange = () => {
        if (!document.hidden && this._isCardVisible() && this._chartLoaded && this._hasChartData() && !this._chart) {
          setTimeout(() => this._createOrUpdateChart(), 200);
        }
      };

      document.addEventListener('visibilitychange', this._handleVisibilityChange);
    }
  }

  // Check if the card is actually visible
  _isCardVisible() {
    if (document.hidden) return false;
    if (!this.isConnected) return false;

    const rect = this.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return false;

    const isInViewport = rect.top < window.innerHeight + 100 &&
                        rect.bottom > -100 &&
                        rect.left < window.innerWidth + 100 &&
                        rect.right > -100;

    const style = getComputedStyle(this);
    const isStyleVisible = style.display !== 'none' &&
                          style.visibility !== 'hidden' &&
                          style.opacity !== '0';

    return isInViewport && isStyleVisible;
  }

  // Load Chart.js library
  async _loadChartJS() {
    if (this._chartLoaded || window.Chart) {
      this._chartLoaded = true;
      return Promise.resolve();
    }

    if (this.chartLoadPromise) {
      return this.chartLoadPromise;
    }

    this.chartLoadPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = 'https://cdn.jsdelivr.net/npm/chart.js@3.9.1/dist/chart.min.js';
      script.onload = () => {
        this._chartLoaded = true;

        if (this._isCardVisible() && this._hasChartData() && !this._chart) {
          setTimeout(() => this._createOrUpdateChart(), 100);
        }

        resolve();
      };
      script.onerror = () => {
        console.error('📊 Failed to load Chart.js for energy usage chart (LitElement)');
        reject(new Error('Failed to load Chart.js'));
      };
      document.head.appendChild(script);
    });

    return this.chartLoadPromise;
  }

  // Detect dark mode
  _detectDarkMode() {
    const isDark = window.getComputedStyle(document.body)
      .getPropertyValue('--primary-background-color')
      .includes('#1');

    if (isDark) {
      this.setAttribute('dark-mode', '');
    } else {
      this.removeAttribute('dark-mode');
    }
  }

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

    const rawData = this._getRawDataForPeriod(entity);
    if (!rawData.length) return;

    // For hourly view, set currentHourlyDate to latest available data BEFORE processing (matches original)
    if (this._currentPeriod === 'hourly' && !this._currentHourlyDate) {
      // Find the latest date in the hourly data
      const sortedData = rawData.sort((a, b) => new Date(b.datetime || b.date) - new Date(a.datetime || a.date));
      if (sortedData.length > 0) {
        const latestDataItem = sortedData[0];
        if (latestDataItem && (latestDataItem.datetime || latestDataItem.date)) {
          const latestDataDate = new Date(latestDataItem.datetime || latestDataItem.date);
          this._currentHourlyDate = latestDataDate;
        }
      }

      // Fallback: if no data available, use yesterday
      if (!this._currentHourlyDate) {
        const yesterday = new Date();
        yesterday.setDate(yesterday.getDate() - 1);
        this._currentHourlyDate = yesterday;
      }
    }

    const canvas = this.shadowRoot.getElementById('energyChart');
    if (!canvas) {
      console.warn('Chart canvas not found, retrying in 100ms...');
    setTimeout(() => {
        if (this.shadowRoot.getElementById('energyChart')) {
          this._createOrUpdateChart();
        }
      }, 100);
      return;
    }

    if (!this._isCardVisible()) {
      return;
    }

    if (canvas.offsetWidth === 0 || canvas.offsetHeight === 0) {
      if (this._isCardVisible()) {
        console.warn('Chart canvas has no dimensions, retrying...');
        setTimeout(() => this._createOrUpdateChart(), 100);
      }
      return;
    }

    // Process data based on period (matches original)
    let labels, usageData, temperatureData, costData, pageData, tempData = [];

    if (this._currentPeriod === 'hourly') {
      // For hourly, process data like original (24 hour labels, filter by current date)
      const processedData = this._processHourlyData(rawData);
      labels = processedData.labels;
      usageData = processedData.usage;
      temperatureData = processedData.temperature;
      pageData = processedData.rawUsage; // For click handling
      costData = pageData.map(item => item.cost || 0);
    } else {
      // For daily/monthly, use pagination like before
      const { pageData: paginatedData } = this._getPaginatedData(rawData);
      pageData = paginatedData;

      // Get temperature data for daily view (matches original)
      if (this._currentPeriod === 'daily') {
        const rawTempData = entity.attributes.recent_temperatures || [];
        const { pageData: tempPageData } = this._getPaginatedData(rawTempData);
        tempData = tempPageData;
      }

      // Prepare chart data (matches original label formatting)
      if (this._currentPeriod === 'monthly') {
        // For monthly period, extend to 6 items to make bars look proportional
        const targetLength = 6;
        const paddedPageData = [...pageData];
        const paddedTempData = [...tempData];

        // Pad with empty data to reach target length
        while (paddedPageData.length < targetLength) {
          paddedPageData.push({ date: null, consumption: 0, usage: 0, cost: 0 });
        }
        while (paddedTempData.length < targetLength) {
          paddedTempData.push({ temperature: 0 });
        }

        labels = paddedPageData.map((item, index) => {
          if (item.date) {
            // Create labels formatted as "24 Jun", "24 Jul" for monthly billing dates (matches original)
            const date = new Date(item.date);
            const day = date.getDate();
            const month = date.toLocaleDateString("en-NZ", { month: "short" });
            return `${day} ${month}`;
      } else {
            // Empty label for padding
            return '';
          }
        });

        usageData = paddedPageData.map(item => item.consumption || item.usage || 0);
        temperatureData = paddedTempData.map(item => item.temperature || 0);
        costData = paddedPageData.map(item => item.cost || 0);
      } else {
        // For daily, use existing logic
        labels = pageData.map(item => {
          // Create labels from usage data (using same format as original daily)
          return new Date(item.date).toLocaleDateString("en-NZ", { weekday: "short" });
        });

        usageData = pageData.map(item => item.consumption || item.usage || 0);
        temperatureData = tempData.map(item => item.temperature || 0);
        costData = pageData.map(item => item.cost || 0);
      }
    }

    // Check if we need to recreate chart due to dataset structure change
    const needsRecreation = this._chart && (
      (this._currentPeriod === 'daily' && this._chart.data.datasets.length !== 2) ||
      (this._currentPeriod !== 'daily' && this._chart.data.datasets.length !== 1)
    );

    // If chart exists and dataset structure is compatible, just update the data
    if (this._chart && this._chart.data && !needsRecreation) {


      this._chart.data.labels = labels;
      this._chart.data.datasets[0].data = usageData;

      // Only update temperature data if the dataset exists (for daily view)
      if (this._chart.data.datasets[1] && this._currentPeriod === 'daily') {
        this._chart.data.datasets[1].data = temperatureData;
      }

      this._chart.update('none');

      // Update chart raw data for interactions
    this.chartRawData = {
        usage: pageData,
        temp: tempData,
        cost: costData
      };


    } else {
      // Create new chart


      if (this._chart) {
        this._chart.destroy();
        this._chart = null;
      }

      // Build datasets based on period (matches original)
      const datasets = this._buildChartDatasets(usageData, temperatureData);

      const ctx = canvas.getContext('2d');
      this._chart = new Chart(ctx, {
        type: 'bar',
      data: {
          labels: labels,
          datasets: datasets
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
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
        plugins: {
            legend: {
            display: false
          },
          tooltip: {
            enabled: false,  // Disable default hover tooltips
            external: (context) => {
                // Custom tooltip that only shows on click, not hover (matches original)
                return; // We handle tooltips manually
            }
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
                }
              },
            title: {
              display: true,
                text: 'kWh',
                color: this._getThemeColor('--primary-text-color'),
                align: 'end',
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
              // Show custom tooltip using actual click position (matches original)
              this._showTemperatureTooltip(event, dataIndex);
              // Update the info display and navigation label
              const selectedItem = this.chartRawData.usage[dataIndex];
              this._updateSelectedInfo(selectedItem);

              // For hourly view, update selected hour and navigation
              if (this._currentPeriod === 'hourly') {
                this._selectedHour = dataIndex; // dataIndex is the hour (0-23)
                this.requestUpdate(); // Trigger navigation label update
              }
              // For daily/monthly view, _updateSelectedInfo already triggers the update
          } else {
            // Click on empty area - hide tooltip but auto-select latest data point
              this._hideCustomTooltip();
              if (this.chartRawData.usage.length > 0) {
                this._updateSelectedInfo(this.chartRawData.usage[this.chartRawData.usage.length - 1]);
            }
          }
        },
        onHover: (event, elements) => {
            // Only change cursor, no hover tooltips (matches original)
          event.native.target.style.cursor = elements.length > 0 ? 'pointer' : 'default';
        }
      }
      });

          // Store chart raw data for interactions
    this.chartRawData = {
      usage: pageData,
      temp: tempData,
      cost: costData
    };
    }

    // Auto-select the latest item if no selection exists
    if (pageData.length > 0 && !this._selectedDate) {
      if (this._currentPeriod === 'hourly') {
        // For hourly, find the latest hour with data and select it (only if no user selection)
        if (!this._selectedHour) {
          const latestHourWithData = pageData.map((item, index) => ({item, hour: index}))
            .reverse()
            .find(({item}) => (item.consumption || item.usage || 0) > 0);

          if (latestHourWithData) {
            this._selectedHour = latestHourWithData.hour;
            this._updateSelectedInfo(latestHourWithData.item);
          } else {
            // Fallback to hour 23 (11pm) if no data
            this._selectedHour = 23;
            this._updateSelectedInfo(this.chartRawData.usage[23] || this.chartRawData.usage[this.chartRawData.usage.length - 1]);
          }
        }
      } else {
        // For daily/monthly, only auto-select if no user selection exists
        if (!this._selectedDate) {
          this._updateSelectedInfo(this.chartRawData.usage[this.chartRawData.usage.length - 1]);
        }
      }
    }
  }




  // Update chart data
  _updateChartData() {
    if (!this._chart) {
      this._createOrUpdateChart();
      return;
    }

    // For hourly data, we need to use the same logic as _createOrUpdateChart to maintain consistency
    if (this._currentPeriod === 'hourly') {
      this._createOrUpdateChart();
      return;
    }

    const entity = this._getEntity();
    if (!entity) return;

    const rawData = this._getRawDataForPeriod(entity);
    const { pageData } = this._getPaginatedData(rawData);

    // Get temperature data for daily view
    let tempData = [];
    if (this._currentPeriod === 'daily') {
      const rawTempData = entity.attributes.recent_temperatures || [];
      const { pageData: tempPageData } = this._getPaginatedData(rawTempData);
      tempData = tempPageData;
    }

    // Update chart data (matches original label formatting) - for daily/monthly only
    let labels, usageData, temperatureData, costData;

    if (this._currentPeriod === 'monthly') {
      // For monthly period, extend to 6 items to make bars look proportional
      const targetLength = 6;
      const paddedPageData = [...pageData];
      const paddedTempData = [...tempData];

      // Pad with empty data to reach target length
      while (paddedPageData.length < targetLength) {
        paddedPageData.push({ date: null, consumption: 0, usage: 0, cost: 0 });
      }
      while (paddedTempData.length < targetLength) {
        paddedTempData.push({ temperature: 0 });
      }

      labels = paddedPageData.map((item, index) => {
        if (item.date) {
          // Create labels formatted as "24 Jun", "24 Jul" for monthly billing dates (matches original)
          const date = new Date(item.date);
      const day = date.getDate();
      const month = date.toLocaleDateString("en-NZ", { month: "short" });
      return `${day} ${month}`;
        } else {
          // Empty label for padding
          return '';
        }
      });

      usageData = paddedPageData.map(item => item.consumption || item.usage || 0);
      temperatureData = paddedTempData.map(item => item.temperature || 0);
      costData = paddedPageData.map(item => item.cost || 0);
    } else {
      // For daily, use existing logic
      labels = pageData.map(item => {
        // Create labels from usage data (using same format as original daily)
        return new Date(item.date).toLocaleDateString("en-NZ", { weekday: "short" });
      });

      usageData = pageData.map(item => item.consumption || item.usage || 0);
      temperatureData = tempData.map(item => item.temperature || 0);
      costData = pageData.map(item => item.cost || 0);
    }

    this._chart.data.labels = labels;
    this._chart.data.datasets[0].data = usageData;

    // Only update temperature data if the dataset exists (for daily view)
    if (this._chart.data.datasets[1] && this._currentPeriod === 'daily') {
      this._chart.data.datasets[1].data = temperatureData;
    }

    this._chart.update('none');

    this.chartRawData = {
      usage: pageData,
      temp: tempData,
      cost: costData
    };

    // Update info display - only auto-select if no user selection exists
    if (this.chartRawData.usage.length > 0 && !this._selectedDate) {
      this._updateSelectedInfo(this.chartRawData.usage[this.chartRawData.usage.length - 1]);
    }

    // Request update to refresh navigation
    this.requestUpdate();
  }

  // Helper method to get theme colors
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

  // Update selected info display
  _updateSelectedInfo(selectedItem) {
    if (!selectedItem) return;

    const date = new Date(selectedItem.date || selectedItem.datetime);
    let dateFormatted;

    if (this._currentPeriod === 'hourly') {
      const hour = date.getHours();
      dateFormatted = `${this._formatHourDisplay(hour)} on ${this._formatDate(date, { weekday: 'long', day: 'numeric', month: 'long' })}`;
    } else if (this._currentPeriod === 'monthly') {
      dateFormatted = this._formatDate(date, { month: 'long', year: 'numeric' });
    } else {
      dateFormatted = this._formatDate(date, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
    }

    this._selectedDate = {
      date: selectedItem.date || selectedItem.datetime, // Store the raw date for navigation label
      dateFormatted,
      cost: selectedItem.cost || 0,
      consumption: selectedItem.consumption || selectedItem.usage || 0,
      // Store full item data for monthly billing period (matches original)
      rawItem: selectedItem
    };

    this.requestUpdate();
  }

  // Handle period change
  _handlePeriodChange(newPeriod) {
    if (newPeriod === this._currentPeriod) return;

    // Hide tooltip when changing periods (matches original)
    this._hideCustomTooltip();

    const previousPeriod = this._currentPeriod;
    this._currentPeriod = newPeriod;

    // Reset states when switching periods
    if (newPeriod === 'hourly' && previousPeriod !== 'hourly') {
      // When switching to hourly, reset to latest available date (will be set in chart creation)
      this._currentHourlyDate = null; // Will be set based on available data
      this._selectedHour = null; // Will be auto-selected to latest hour with data
      this._currentPage = 0;
      this._selectedDate = null;
    } else if (newPeriod !== 'hourly' && previousPeriod === 'hourly') {
      // When switching away from hourly, clear hourly state
      this._currentPage = 0;
      this._selectedDate = null;
      this._selectedHour = null;
      this._currentHourlyDate = null; // Clear hourly date to prevent state leakage
    } else {
      this._currentPage = 0;
      this._selectedDate = null;
    }

    // Recreate chart with new period data
    this._createOrUpdateChart();
    this.requestUpdate();
  }

    // Handle navigation
  _handleNavigation(direction) {
    // Hide tooltip when navigating
    this._hideCustomTooltip();

    const entity = this._getEntity();
    if (!entity) return;

    const rawData = this._getRawDataForPeriod(entity);

    if (this._currentPeriod === 'hourly') {
      // For hourly, navigate by days
      const uniqueDates = [...new Set(rawData.map(item => new Date(item.datetime || item.date).toISOString().split('T')[0]))]
        .sort().reverse(); // Newest first

      const currentDateStr = this._currentHourlyDate.toISOString().split('T')[0];
      const currentIndex = uniqueDates.indexOf(currentDateStr);

      if (direction === 'next' && currentIndex > 0) {
        this._currentHourlyDate = new Date(uniqueDates[currentIndex - 1]);
        this._selectedDate = null; // Clear selection to trigger auto-selection
        this._selectedHour = null; // Clear hour selection to trigger auto-selection
        this._createOrUpdateChart();
      } else if (direction === 'prev' && currentIndex < uniqueDates.length - 1) {
        this._currentHourlyDate = new Date(uniqueDates[currentIndex + 1]);
        this._selectedDate = null; // Clear selection to trigger auto-selection
        this._selectedHour = null; // Clear hour selection to trigger auto-selection
        this._createOrUpdateChart();
      }
        } else {
      // For daily/monthly, use page navigation
      const maxPage = Math.ceil(rawData.length / this.itemsPerPage) - 1;

      if (direction === 'next' && this._currentPage > 0) {
        this._currentPage--;
        this._selectedDate = null; // Clear selection to trigger auto-selection
        this._updateChartData();
      } else if (direction === 'prev' && this._currentPage < maxPage) {
        this._currentPage++;
        this._selectedDate = null; // Clear selection to trigger auto-selection
        this._updateChartData();
      }
    }
  }

  // Auto-select the latest data point for current period
  _autoSelectLatestDataPoint() {
    const entity = this._getEntity();
    if (!entity) return;

    const rawData = this._getRawDataForPeriod(entity);
    if (!rawData.length) return;

    if (this._currentPeriod === 'hourly') {
      // For hourly, auto-selection is handled in _createOrUpdateChart
      return;
    }

    // For daily/monthly, get the current page data and select the latest
    // Only auto-select if no user selection exists
    const { pageData } = this._getPaginatedData(rawData);
    if (pageData.length > 0 && !this._selectedDate) {
      this._updateSelectedInfo(pageData[pageData.length - 1]);
    }
  }

  // Check if there's previous page data (matches original hasPreviousPageData)
  _hasPreviousPageData() {
    const entity = this._getEntity();
    if (!entity) return false;

    // For hourly view, check if there's data for the previous day
    if (this._currentPeriod === 'hourly') {
      if (!this._currentHourlyDate) {
        return false; // No navigation until date is set
      }

      const rawHourlyData = entity.attributes.hourly_usage_history || [];
      if (rawHourlyData.length === 0) {
        return false; // No hourly data available
      }

      // Get the previous day
      const previousDay = new Date(this._currentHourlyDate);
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
    if (this._currentPeriod === 'monthly') {
      const rawMonthlyData = entity.attributes.monthly_usage_history || [];
      const nextPageStartIndex = (this._currentPage + 1) * this.itemsPerPage;
      return rawMonthlyData.length > nextPageStartIndex;
    }

    // For daily view, check daily data
    const rawUsageData = entity.attributes.daily_usage_history || [];
    // Check if there's more data beyond the current page (older data)
    const nextPageStartIndex = (this._currentPage + 1) * this.itemsPerPage;
    return rawUsageData.length > nextPageStartIndex;
  }

  // Check if there's next page data (matches original hasNextPageData)
  _hasNextPageData() {
    // For hourly view, check if we can go to next day and if there's data available
    if (this._currentPeriod === 'hourly') {
      if (!this._currentHourlyDate) {
        return false; // No navigation until date is set
      }

      const entity = this._getEntity();
      if (!entity) return false;

      const tomorrow = new Date(this._currentHourlyDate);
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
    if (this._currentPeriod === 'monthly') {
      return this._currentPage > 0;
    }

    // For daily view, next means newer data, only available if we're not on page 0
    return this._currentPage > 0;
  }

  // Check if navigation buttons should be disabled
  _isNavDisabled(direction) {
    if (direction === 'prev') {
      return !this._hasPreviousPageData();
    } else if (direction === 'next') {
      return !this._hasNextPageData();
    }
    return false;
  }

  // Get navigation description based on current period and selected date
  _getNavigationDescription() {
    const entity = this._getEntity();
    if (!entity) return 'No data available';

    try {
            if (this._currentPeriod === 'hourly') {
        // For hourly view, show date and selected hour (matches original format)
        if (!this._currentHourlyDate) return 'No hourly data available';

        const dateStr = this._currentHourlyDate.toLocaleDateString("en-NZ", {
          day: 'numeric',
          month: 'short',
          year: 'numeric'
        });

        // Always show hour - use selected hour if available, otherwise default to latest hour
        let hourToShow = this._selectedHour;
        if (hourToShow === null || hourToShow === undefined) {
          // Default to current hour or 23 (11pm) if no selection
          hourToShow = new Date().getHours();
        }

        const hourDisplay = this._formatHourDisplay(hourToShow);
        return `${dateStr}\n${hourDisplay}`;
      } else if (this._currentPeriod === 'monthly') {
        // For monthly view, show the billing period date range (matches original)

        // If a specific item is selected, show its billing period (matches original behavior)
        if (this._selectedDate && this._selectedDate.rawItem) {
          const selectedItem = this._selectedDate.rawItem;
          if (selectedItem.invoiceFrom && selectedItem.invoiceTo) {
            const fromDate = new Date(selectedItem.invoiceFrom);
            const toDate = new Date(selectedItem.invoiceTo);
            const fromFormatted = fromDate.toLocaleDateString("en-NZ", { day: 'numeric', month: 'short', year: 'numeric' });
            const toFormatted = toDate.toLocaleDateString("en-NZ", { day: 'numeric', month: 'short', year: 'numeric' });
            return `${fromFormatted} - ${toFormatted}\n&nbsp;`;
          }
        }

        // Otherwise, show the billing period of the latest entry from current page
        const rawData = entity.attributes.monthly_usage_history || [];
        const { pageData } = this._getPaginatedData(rawData);

        if (pageData.length === 0) return 'No monthly data available';

        // Get the latest entry from current page
        const latestEntry = pageData[0];
        if (latestEntry && latestEntry.invoiceFrom && latestEntry.invoiceTo) {
        const fromDate = new Date(latestEntry.invoiceFrom);
        const toDate = new Date(latestEntry.invoiceTo);
          const fromFormatted = fromDate.toLocaleDateString("en-NZ", { day: 'numeric', month: 'short', year: 'numeric' });
          const toFormatted = toDate.toLocaleDateString("en-NZ", { day: 'numeric', month: 'short', year: 'numeric' });
          return `${fromFormatted} - ${toFormatted}\n&nbsp;`;
        }

        // Fallback to date range if invoiceFrom/invoiceTo not available
        const startDate = new Date(pageData[pageData.length - 1].date);
        const endDate = new Date(pageData[0].date);
        const startStr = startDate.toLocaleDateString("en-NZ", { month: 'short', year: 'numeric' });
        const endStr = endDate.toLocaleDateString("en-NZ", { month: 'short', year: 'numeric' });
        const dateRange = startStr === endStr ? startStr : `${startStr} - ${endStr}`;
        return `${dateRange}\n&nbsp;`;
      } else {
        // For daily view, show specific selected date if available, otherwise show latest date from current page
        if (this._selectedDate && this._selectedDate.date) {
          // Show the selected date in format "16 Aug 2025" with newline and nbsp for consistent height
          const selectedDate = new Date(this._selectedDate.date);
          const dateStr = selectedDate.toLocaleDateString("en-NZ", {
            day: 'numeric',
            month: 'short',
            year: 'numeric'
          });
          return `${dateStr}\n&nbsp;`;
        } else {
          // Show the latest date from current page (newest date)
          const rawData = entity.attributes.daily_usage_history || [];
          const { pageData } = this._getPaginatedData(rawData);

          if (pageData.length === 0) return 'No daily data available';

          // pageData is sorted newest first, so pageData[0] is the latest date
          const latestDate = new Date(pageData[0].date);
          const dateStr = latestDate.toLocaleDateString("en-NZ", {
            day: 'numeric',
            month: 'short',
            year: 'numeric'
          });
          return `${dateStr}\n&nbsp;`;
        }
      }
    } catch (error) {
      console.error('Error generating navigation description:', error);
      return 'Data unavailable';
    }
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

    // Check if we have chart data
    if (!this._hasChartData()) {
      return this._renderLoadingState('Loading Chart Data...', '📊');
    }

    // Render the main card
    return this._renderEnergyUsageCard(entity);
  }

  // Render loading state
  _renderLoadingState(message, icon = '⏳') {
    return html`
      <ha-card>
        <div class="loading-state">
          <div class="loading-message">${icon} ${message}</div>
          <div class="loading-description">Mercury Energy chart data is loading</div>
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
          <div class="loading-description" style="margin-bottom: 15px;">Please configure an entity for this Mercury Energy chart</div>
          <div style="font-size: 0.7em; background: var(--secondary-background-color, #f5f5f5); padding: 10px; border-radius: 4px; text-align: left;">
            <strong>Example configuration:</strong><br/>
            type: custom:mercury-energy-usage-card<br/>
            entity: sensor.mercury_nz_energy_usage
          </div>
        </div>
      </ha-card>
    `;
  }

  _renderEnergyUsageCard(entity) {
    const rawData = this._getRawDataForPeriod(entity);
    const showNavigation = this.config.show_navigation && this._shouldShowNavigation(rawData);

    return html`
      <ha-card class="mercury-chart-card">
        <div class="card-content">
          <div class="header">
            <div class="title-row">
              <h3>${this.config.name}</h3>
            </div>
          </div>

          ${this.allowedPeriods.length > 1 ? this._renderPeriodSelector() : ''}

          ${showNavigation ? this._renderNavigation() : ''}

          <div class="chart-container">
            <canvas id="energyChart" width="400" height="200"></canvas>
          </div>

          ${this._renderCustomLegend()}

          <div class="chart-info">
            <div class="data-info">
              ${this._selectedDate ? html`
                <div class="usage-details">
                  <div class="usage-date">${this._currentPeriod === 'monthly' ? 'Your usage this billing period' : `Your usage on ${this._selectedDate.dateFormatted}`}</div>
                  <div class="usage-stats">$${this._selectedDate.cost.toFixed(2)} | ${this._selectedDate.consumption.toFixed(2)} kWh</div>
                </div>
              ` : html`Loading...`}
            </div>
          </div>
        </div>
      </ha-card>
    `;
  }

  _renderPeriodSelector() {
    const periodLabels = {
      'hourly': 'HOURLY',
      'daily': 'DAILY',
      'monthly': 'MONTHLY'
    };

    return html`
      <div class="time-period-selector">
        ${this.allowedPeriods.map(period => html`
          <button
            class="period-btn ${period === this._currentPeriod ? 'active' : ''}"
            @click=${() => this._handlePeriodChange(period)}
          >
            ${periodLabels[period]}
          </button>
        `)}
      </div>
    `;
  }

  _renderNavigation() {
    const description = this._getNavigationDescription();
    // Handle newlines in description for hourly view (matches original)
    const formattedDescription = description.replace(/\n/g, '<br/>');

    return html`
      <div class="navigation">
        <div class="nav-info">
          <div class="nav-date-container">
            <div class="nav-column nav-column-left">
              <span
                class="nav-arrow ${this._isNavDisabled('prev') ? 'nav-arrow-hidden' : ''}"
                @click=${() => !this._isNavDisabled('prev') && this._handleNavigation('prev')}
              >&lt;</span>
            </div>
            <div class="nav-column nav-column-center">
              <span class="nav-date" .innerHTML=${formattedDescription}></span>
            </div>
            <div class="nav-column nav-column-right">
              <span
                class="nav-arrow ${this._isNavDisabled('next') ? 'nav-arrow-hidden' : ''}"
                @click=${() => !this._isNavDisabled('next') && this._handleNavigation('next')}
              >&gt;</span>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderCustomLegend() {
    // Generate custom legend HTML based on current period (matches original generateCustomLegendHTML)
    const actualLegend = html`
      <div class="legend-item">
        <div class="legend-circle"></div>
        <span class="legend-label">Actual</span>
      </div>
    `;

    const temperatureLegend = html`
      <div class="legend-item">
        <div class="legend-line"></div>
        <span class="legend-label">Average Temperature</span>
      </div>
    `;

    // Only show temperature legend for daily view (matches original)
    const showTemperature = this._currentPeriod === 'daily';

    return html`
      <div class="custom-legend">
        ${actualLegend}
        ${showTemperature ? temperatureLegend : ''}
      </div>
    `;
  }

  // getCardSize() inherited from mercuryLitCore (defaults to 6)
}

// Register the custom element
if (!customElements.get('mercury-energy-usage-card')) {
  customElements.define('mercury-energy-usage-card', MercuryEnergyUsageCard);
}

// Add to Home Assistant custom cards registry if available
if (window.customCards) {
window.customCards = window.customCards || [];
  window.customCards.push({
    type: 'mercury-energy-usage-card',
    name: 'Mercury Energy Usage Card',
    description: 'Energy usage chart card for Mercury Energy NZ built with LitElement',
    preview: false,
    documentationURL: 'https://github.com/bkintanar/home-assistant-mercury-co-nz'
  });
}

console.info(
  '%c MERCURY-ENERGY-USAGE-CARD %c v1.0.0 ',
  'color: orange; font-weight: bold; background: black',
  'color: white; font-weight: bold; background: dimgray'
);
