// chartjs-custom-card.js
// Save to /config/www/chartjs-custom-card.js

class ChartJSCustomCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.currentPage = 0;
    this.itemsPerPage = 12;
    this.chart = null;
    this.chartLoaded = false;
    this.chartLoadPromise = null;
    this.loadRetryCount = 0;
    this.maxLoadRetries = 3;
    this.stickyTooltip = false;
    this.selectedDate = null; // Track the currently selected date
    this.isRendering = false;
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
      cost_per_kwh: 0.25, // Default cost per kWh for calculations
      colors: {
        usage: '#FFF000',
        temperature: '#69A2B9'
      },
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
        script.src = 'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.js';

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
            console.log('📊 Chart.js loaded successfully');
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

    const entity = this._hass.states[this.config.entity];

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

    // Only do full render if DOM doesn't exist yet or if chart was destroyed
    if (!this.shadowRoot.querySelector('ha-card') || !this.chart) {
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

        <div class="chart-info">
          <div class="data-info">
            ${this.getLatestDateDescription()}
          </div>
        </div>
      </ha-card>
    `;

    this.attachEventListeners();
    this.createChart(entity);
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

    const dataInfo = this.shadowRoot.querySelector('.data-info');
    if (dataInfo) {
      this.resetInfoDisplay();
    }

    // Get updated data
    const rawUsageData = entity.attributes.daily_usage_history || [];
    const rawTempData = entity.attributes.recent_temperatures || [];
    const chartData = this.processChartData(rawUsageData, rawTempData);



    // Update chart data without destroying/recreating
    this.chart.data.labels = chartData.labels;
    this.chart.data.datasets[0].data = chartData.usage;
    this.chart.data.datasets[1].data = chartData.temperature;



    // Update chart theme colors in case theme changed
    this.updateChartTheme();

    // Store raw data for click events
    this.chartRawData = {
      usage: chartData.rawUsage,
      temp: chartData.rawTemp
    };

        // Animate the update (use 'none' to prevent any animation-related scrolling)
    console.log('📊 Chart data being set:', {
      labels: this.chart.data.labels,
      usageData: this.chart.data.datasets[0].data,
      firstDate: this.chart.data.labels[0],
      lastDate: this.chart.data.labels[this.chart.data.labels.length - 1]
    });
    this.chart.update('none');
    console.log('📊 Chart update completed');

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
      // Get data from your mercury energy sensor - matching your ApexCharts setup
      const rawUsageData = entity.attributes.daily_usage_history || [];
      const rawTempData = entity.attributes.recent_temperatures || [];

      // If no fresh data available but we have cached data, use it
      if ((!rawUsageData.length || !rawTempData.length) && this.lastKnownData) {
        console.log('📊 Using cached data during reconnection');
        // We'll still create the chart but with a loading indicator
      }

    // Process data for current page
    const chartData = this.processChartData(rawUsageData, rawTempData);

    const canvas = this.shadowRoot.getElementById('energyChart');
    const ctx = canvas.getContext('2d');

    // Destroy existing chart if it exists
    if (this.chart) {
      this.chart.destroy();
    }

    // Store raw data for click events
    this.chartRawData = {
      usage: chartData.rawUsage,
      temp: chartData.rawTemp
    };

    // Create new Chart.js chart
    this.chart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: chartData.labels,
        datasets: [
          {
            label: 'Usage (kWh)',
            data: chartData.usage,
            backgroundColor: 'rgba(255, 240, 0, 0.8)',
            borderColor: '#FFF000',
            borderWidth: 2,
            borderRadius: {
              topLeft: 3,
              topRight: 3,
              bottomLeft: 0,
              bottomRight: 0
            },
            type: 'bar',
            yAxisID: 'y',
            order: 2  // Higher number = rendered behind
          },
          {
            label: 'Temperature (°C)',
            data: chartData.temperature,
            backgroundColor: 'rgba(105, 162, 185, 0.1)',
            borderColor: 'rgb(105, 162, 185)',
            borderWidth: 3,
            type: 'line',
            fill: false,
            tension: 0.4,
            pointRadius: 0,        // Remove circles
            pointHoverRadius: 0,   // Remove hover circles
            yAxisID: 'y',
            order: 1  // Lower number = rendered on top
          }
        ]
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
    });

    // Auto-select the latest data point (last index since data is sorted oldest to newest)
    if (chartData.usage.length > 0) {
      const latestIndex = chartData.usage.length - 1;
      this.handleChartClick(latestIndex);
    }

    } catch (error) {
      console.error('📊 Error creating chart:', error);
      this.showErrorState('Failed to create chart: ' + error.message);
    }
  }

  processChartData(usageData, tempData) {
    // Sort data newest first for pagination calculation
    const sortedUsageData = usageData.sort((a, b) => new Date(b.date) - new Date(a.date));
    const sortedTempData = tempData.sort((a, b) => new Date(b.date) - new Date(a.date));

        // Smart pagination logic
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

    // Slice the data based on calculated indices
    const sortedUsage = sortedUsageData
      .slice(startIndex, endIndex)
      .sort((a, b) => new Date(a.date) - new Date(b.date)); // Re-sort oldest first for chart display

    const sortedTemp = sortedTempData
      .slice(startIndex, endIndex)
      .sort((a, b) => new Date(a.date) - new Date(b.date)); // Re-sort oldest first for chart display

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
    const chartContainer = this.shadowRoot.querySelector('.chart-container');
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
    const tempData = this.chart.data.datasets[1].data;

    const usageValue = usageData[dataIndex];
    const tempValue = tempData[dataIndex];

    // Get the actual date from raw data
    const usageDate = this.chartRawData.usage[dataIndex]?.date;
    const tempDate = this.chartRawData.temp[dataIndex]?.date;
    const date = usageDate || tempDate || new Date().toISOString();

    // Update the info area instead of showing popup
    this.updateInfoDisplay(date, usageValue, tempValue);
  }

  updateInfoDisplay(date, usage, temperature) {
    const dataInfo = this.shadowRoot.querySelector('.data-info');
    if (!dataInfo) return;

    // Store the selected date
    this.selectedDate = date;

    // Format the date for the top line (same format as getLatestDateDescription)
    const dateObj = new Date(date);
    const selectedDate = dateObj.toLocaleDateString("en-NZ", {
      day: 'numeric',
      month: 'short',
      year: 'numeric'
    });

    // Format the date nicely for the detailed view
    const formattedDate = dateObj.toLocaleDateString("en-NZ", {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
      year: 'numeric'
    });

    // Calculate estimated cost (assuming $0.25 per kWh - you can adjust this)
    const costPerKwh = this.config.cost_per_kwh || 0.25;
    const estimatedCost = usage * costPerKwh;

    // Update the navigation date
    const navDate = this.shadowRoot.querySelector('#navDate');
    if (navDate) {
      navDate.textContent = selectedDate;
    }

    // Update the display to show selected date at top and details below
    dataInfo.innerHTML = `
      <div class="usage-details">
        <div class="usage-date">Your usage on ${formattedDate}</div>
        <div class="usage-stats">$${estimatedCost.toFixed(2)} | ${usage.toFixed(2)} kWh</div>
      </div>
    `;
  }

  resetInfoDisplay() {
    // Clear the selected date
    this.selectedDate = null;

    // Update the navigation date
    const navDate = this.shadowRoot.querySelector('#navDate');
    if (navDate) {
      navDate.textContent = this.getCurrentDateDescription();
    }

    const dataInfo = this.shadowRoot.querySelector('.data-info');
    if (dataInfo) {
      dataInfo.innerHTML = `${this.getLatestDateDescription()}`;
    }
  }

  exportData() {
    // Export current page data as CSV
    if (!this._hass || !this.config.entity) return;

    const entity = this._hass.states[this.config.entity];
    const rawUsageData = entity.attributes.daily_usage_history || [];
    const rawTempData = entity.attributes.recent_temperatures || [];

    // Create CSV content
    let csvContent = "Date,Usage (kWh),Temperature (°C),Estimated Cost\n";

    // Smart pagination logic for CSV export (same as chart data)
    const sortedUsageData = rawUsageData.sort((a, b) => new Date(b.date) - new Date(a.date));
    const sortedTempData = rawTempData.sort((a, b) => new Date(b.date) - new Date(a.date));

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

    const sortedUsage = sortedUsageData
      .slice(startIndex, endIndex)
      .sort((a, b) => new Date(a.date) - new Date(b.date));

    const sortedTemp = sortedTempData
      .slice(startIndex, endIndex)
      .sort((a, b) => new Date(a.date) - new Date(b.date));

    const costPerKwh = this.config.cost_per_kwh || 0.25;

    sortedUsage.forEach((usage, index) => {
      const temp = sortedTemp[index];
      const cost = (Number(usage.consumption) * costPerKwh).toFixed(2);
      csvContent += `${usage.date},${usage.consumption},${temp?.temperature || 'N/A'},$${cost}\n`;
    });

    // Download CSV
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `energy-data-page-${this.currentPage + 1}.csv`;
    a.click();
    window.URL.revokeObjectURL(url);
  }

  hasPreviousPageData() {
    if (!this._hass || !this.config.entity) return false;

    const entity = this._hass.states[this.config.entity];
    if (!entity) return false;

    const rawUsageData = entity.attributes.daily_usage_history || [];
    // Check if there's more data beyond the current page (older data)
    const nextPageStartIndex = (this.currentPage + 1) * this.itemsPerPage;
    return rawUsageData.length > nextPageStartIndex;
  }

  hasNextPageData() {
    // Next means newer data, only available if we're not on page 0
    return this.currentPage > 0;
  }

  updateNavigation() {
    const navContainer = this.shadowRoot.querySelector('.navigation');
    if (navContainer && this.config.show_navigation) {
      navContainer.innerHTML = this.getNavigationHTML();
      this.attachEventListeners(); // Re-attach event listeners to new elements
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
        <span class="nav-date-container">
          ${hasPrevData ? `<span class="nav-arrow" id="prevBtn">&lt;</span> ` : ''}
          <span id="navDate">${dateText}</span>
          ${hasNextData ? ` <span class="nav-arrow" id="nextBtn">&gt;</span>` : ''}
        </span>
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
    if (!this._hass || !this.config.entity) return 'No data available';

    const entity = this._hass.states[this.config.entity];
    if (!entity) return 'No data available';

    const rawUsageData = entity.attributes.daily_usage_history || [];
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

    // Get the most recent date from the current page (first item since sorted newest first)
    const latestDate = new Date(sortedUsage[0].date);
    const formattedDate = latestDate.toLocaleDateString("en-NZ", {
      day: 'numeric',
      month: 'short',
      year: 'numeric'
    });

    return formattedDate;
  }

  getCurrentDateDescription() {
    // Return selected date if available, otherwise return latest date
    if (this.selectedDate) {
      const dateObj = new Date(this.selectedDate);
      return dateObj.toLocaleDateString("en-NZ", {
        day: 'numeric',
        month: 'short',
        year: 'numeric'
      });
    }
    return this.getLatestDateDescription();
  }

  getPageDescription() {
    if (this.currentPage === 0) return 'Latest Data';
    return `${this.currentPage * this.itemsPerPage} days ago`;
  }

  attachEventListeners() {
    const prevBtn = this.shadowRoot.getElementById('prevBtn');
    const nextBtn = this.shadowRoot.getElementById('nextBtn');

    if (prevBtn) {
            prevBtn.addEventListener('click', () => {
        console.log('🔙 PREV CLICKED - before:', this.currentPage);
        this.hideCustomTooltip(); // Hide tooltip when navigating
        this.currentPage++;
        this.selectedDate = null; // Clear selected date when changing pages
        console.log('🔙 PREV CLICKED - after:', this.currentPage);

        // Get the entity and update chart data
        const entity = this._hass.states[this.config.entity];
        console.log('🔙 Entity check:', !!entity, entity?.attributes?.daily_usage_history?.length);
        this.updateChartData(entity);
        console.log('🔙 updateChartData called');
      });
    }

    if (nextBtn) {
      nextBtn.addEventListener('click', () => {
        if (this.currentPage > 0) {

          this.hideCustomTooltip(); // Hide tooltip when navigating
          this.currentPage--;
          this.selectedDate = null; // Clear selected date when changing pages


          // Get the entity and update chart data
          const entity = this._hass.states[this.config.entity];
          this.updateChartData(entity);
        }
      });
    }

    // Add event listeners for time period buttons
    const periodButtons = this.shadowRoot.querySelectorAll('.period-btn');
    periodButtons.forEach(button => {
      button.addEventListener('click', () => {
        // Remove active class from all buttons
        periodButtons.forEach(btn => btn.classList.remove('active'));
        // Add active class to clicked button
        button.classList.add('active');

        const period = button.dataset.period;
        console.log(`Selected period: ${period}`);
        // TODO: Implement period switching logic here
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
          margin-bottom: 16px;
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
          background: #e8f4f8;
          border-radius: 20px;
          padding: 4px;
          max-width: 300px;
          margin-left: auto;
          margin-right: auto;
        }

        .period-btn {
          flex: 1;
          background: transparent;
          border: none;
          padding: 8px 16px;
          border-radius: 16px;
          font-weight: 600;
          font-size: 12px;
          cursor: pointer;
          transition: all 0.2s ease;
          color: var(--secondary-text-color);
          text-transform: uppercase;
        }

        .period-btn.active {
          background: #FFF000;
          color: #000;
          box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }

        .period-btn:hover:not(.active) {
          background: rgba(255, 255, 255, 0.5);
        }

        .navigation {
          display: flex;
          justify-content: center;
          align-items: center;
          padding: 12px 0;
          border-bottom: 1px solid var(--divider-color);
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

        .chart-container {
          height: 400px;
          margin: 20px 0;
          background: var(--card-background-color, white);
          border-radius: 4px;
          padding: 10px;
          position: relative;  /* Enable relative positioning for tooltips */
        }

        .chart-info {
          text-align: center;
          margin-top: 12px;
          padding-top: 12px;
          border-top: 1px solid var(--divider-color);
          min-height: 48px;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .data-info {
          font-size: 12px;
          color: var(--secondary-text-color);
        }

        .usage-details {
          text-align: center;
        }

        .usage-date {
          font-size: 14px;
          font-weight: 500;
          color: var(--primary-text-color);
          margin-bottom: 4px;
        }

        .usage-stats {
          font-size: 16px;
          font-weight: 600;
          color: var(--primary-color);
        }
      </style>
    `;
  }

  getCardSize() {
    return 5;
  }

  // Add method to preserve chart state during reconnection
  preserveChartState() {
    if (this.chart && this.chart.data) {
      this.lastKnownData = {
        labels: [...this.chart.data.labels],
        usage: [...this.chart.data.datasets[0].data],
        temperature: [...this.chart.data.datasets[1].data]
      };
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
  '%c  MERCURY-ENERGY-CHART-CARD  \n%c  Version 1.0.0       ',
  'color: orange; font-weight: bold; background: black',
  'color: white; font-weight: bold; background: dimgray'
);
