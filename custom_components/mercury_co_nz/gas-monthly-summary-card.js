// Mercury Gas Monthly Summary Card for Home Assistant (LitElement)
// Monthly bar chart with prev/next nav for gas consumption.
// Bars are colored per-period: yellow for actual reads, gray for estimates.
// Mirrors the monthly mode of energy-usage-card.js but specialized for gas
// (no period switcher, no temperature overlay).

import { LitElement, html, css } from 'https://unpkg.com/lit@3.1.0/index.js?module';
import { mercuryChartStyles, mercuryColors } from './styles.js';
import { mercuryLitCore } from './core.js';

class MercuryGasMonthlySummaryCard extends LitElement {
  static styles = [
    mercuryChartStyles,
    css`
      /* Gas card-specific overrides. The chart-info background reflects the
         selected period's read type — yellow for actual reads, gray for
         Mercury estimates — matching the bar color. */
      .chart-info.estimate {
        background: #727272;
      }
      .chart-info.estimate .usage-date,
      .chart-info.estimate .usage-stats {
        color: white;
      }

      /* Single-row layout: "🔥 Your gas usage for this billing period   $X.XX | XXX kWh"
         falls back to wrapped on narrow screens. */
      .usage-details {
        display: flex;
        flex-wrap: wrap;
        align-items: baseline;
        gap: 16px;
      }
      .usage-date {
        margin-bottom: 0;
      }
      .usage-stats {
        font-weight: 600;
      }

      .fire-emoji {
        margin-right: 6px;
        font-size: 16px;
        line-height: 1;
      }
    `
  ];

  static properties = {
    hass: { type: Object },
    config: { type: Object },
    _entity: { type: Object, state: true },
    _chartLoaded: { type: Boolean, state: true },
    _chart: { type: Object, state: true },
    _currentPage: { type: Number, state: true },
    _selectedDate: { type: Object, state: true }
  };

  constructor() {
    super();
    Object.assign(this, mercuryLitCore);
    this.initializeBase();

    this._currentPage = 0;
    this._selectedDate = null;
    this.itemsPerPage = 6;

    // Initialised here so the Chart.js onClick callback never reads
    // undefined if a click somehow arrives before the chart is built.
    this.chartRawData = { usage: [] };

    this.CHART_COLORS = {
      ...this.CHART_COLORS,
      ...mercuryColors
    };

    this._setupVisibilityObserver();
  }

  setConfig(config) {
    this.config = this.setConfigBase(config, 'Gas Monthly Usage');
    this.config = {
      show_navigation: true,
      ...this.config
    };
  }

  connectedCallback() {
    super.connectedCallback();
    this.setupLifecycleBase();
  }

  firstUpdated() {
    super.firstUpdated();
    this._hasChartData = this._hasChartData.bind(this);
    this.handleFirstUpdatedBase();
  }

  updated(changedProps) {
    super.updated(changedProps);
    this.handleUpdatedBase(changedProps);

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

  _hasChartData() {
    const entity = this._getEntity();
    if (!entity || !entity.attributes) return false;
    const history = entity.attributes.gas_monthly_usage_history;
    return Array.isArray(history) && history.length > 0;
  }

  _getRawData(entity) {
    return entity.attributes.gas_monthly_usage_history || [];
  }

  // Sort newest-first for pagination, page slice oldest-first for chart left-to-right.
  _getPaginatedData(rawData) {
    if (!rawData.length) return { sortedData: [], pageData: [] };

    const sortedData = [...rawData].sort(
      (a, b) => new Date(b.invoice_to || b.date) - new Date(a.invoice_to || a.date)
    );

    let startIndex = this._currentPage * this.itemsPerPage;
    let endIndex = Math.min(startIndex + this.itemsPerPage, sortedData.length);

    // When the last page has fewer than itemsPerPage entries, slide the
    // window back so we always show a full page if data permits.
    const maxPage = Math.ceil(sortedData.length / this.itemsPerPage) - 1;
    if (this._currentPage === maxPage && sortedData.length >= this.itemsPerPage) {
      const remainingItems = sortedData.length - startIndex;
      if (remainingItems < this.itemsPerPage) {
        endIndex = sortedData.length;
        startIndex = Math.max(0, endIndex - this.itemsPerPage);
      }
    }

    const pageData = sortedData
      .slice(startIndex, endIndex)
      .sort((a, b) => new Date(a.invoice_to || a.date) - new Date(b.invoice_to || b.date));

    return { sortedData, pageData };
  }

  // Pad to itemsPerPage so bar widths stay proportional when fewer than 6 periods exist.
  _padPageData(pageData) {
    const padded = [...pageData];
    while (padded.length < this.itemsPerPage) {
      padded.push({ date: null, consumption: 0, cost: 0, is_estimated: false });
    }
    return padded;
  }

  _formatChartLabels(paddedData) {
    return paddedData.map((item) => {
      const dateStr = item.invoice_to || item.date;
      if (!dateStr) return '';
      const date = new Date(dateStr);
      const day = date.getDate();
      const month = date.toLocaleDateString('en-NZ', { month: 'short' });
      return `${day} ${month}`;
    });
  }

  _buildBarColors(paddedData) {
    return paddedData.map((item) =>
      item.is_estimated === true
        ? this.CHART_COLORS.SECONDARY_GRAY
        : this.CHART_COLORS.PRIMARY_YELLOW
    );
  }

  _buildDatasets(usageData, barColors) {
    return [{
      label: 'Gas Usage (kWh)',
      data: usageData,
      backgroundColor: barColors,
      borderColor: barColors,
      borderWidth: 2,
      borderRadius: { topLeft: 3, topRight: 3, bottomLeft: 0, bottomRight: 0 },
      barPercentage: 0.9,
      type: 'bar',
      yAxisID: 'y',
      order: 1
    }];
  }

  // Single source of truth for chart-data derivation. Used by both the
  // create path (_createOrUpdateChart) and the update path (_updateChartData).
  _buildChartView(rawData) {
    const { pageData } = this._getPaginatedData(rawData);
    const paddedData = this._padPageData(pageData);
    return {
      pageData,
      labels: this._formatChartLabels(paddedData),
      usageData: paddedData.map((item) => item.consumption || 0),
      barColors: this._buildBarColors(paddedData)
    };
  }

  async _createOrUpdateChart() {
    if (!this._chartLoaded) {
      await this._loadChartJS();
    }
    await this.updateComplete;

    const entity = this._getEntity();
    if (!entity || !entity.attributes) return;

    const rawData = this._getRawData(entity);
    if (!rawData.length) return;

    const canvas = this.shadowRoot.getElementById('gasChart');
    if (!canvas) {
      setTimeout(() => {
        if (this.shadowRoot.getElementById('gasChart')) this._createOrUpdateChart();
      }, 100);
      return;
    }

    if (!this._isCardVisible()) return;

    if (canvas.offsetWidth === 0 || canvas.offsetHeight === 0) {
      if (this._isCardVisible()) {
        setTimeout(() => this._createOrUpdateChart(), 100);
      }
      return;
    }

    // If a chart already exists, delegate the data refresh to _updateChartData
    // so the dataset-update logic lives in one place.
    if (this._chart && this._chart.data) {
      this._updateChartData();
      return;
    }

    if (this._chart) {
      this._chart.destroy();
      this._chart = null;
    }

    const { pageData, labels, usageData, barColors } = this._buildChartView(rawData);
    const datasets = this._buildDatasets(usageData, barColors);
    const ctx = canvas.getContext('2d');
    this._chart = new Chart(ctx, {
      type: 'bar',
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 1500, easing: 'easeOutCubic' },
        plugins: {
          legend: { display: false },
          tooltip: { enabled: false }
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: {
              color: this._getThemeColor('--secondary-text-color'),
              font: { size: 12 }
            }
          },
          y: {
            beginAtZero: true,
            grid: { color: this._getThemeColor('--divider-color', 0.3) },
            ticks: {
              color: this._getThemeColor('--secondary-text-color'),
              font: { size: 11 }
            },
            title: {
              display: true,
              text: 'kWh',
              color: this._getThemeColor('--primary-text-color'),
              align: 'end',
              font: { size: 12, weight: 600 }
            }
          }
        },
        onClick: (event, elements) => {
          if (elements.length > 0) {
            const dataIndex = elements[0].index;
            const selectedItem = this.chartRawData.usage[dataIndex];
            if (selectedItem) this._updateSelectedInfo(selectedItem);
          } else if (this.chartRawData.usage.length > 0) {
            this._updateSelectedInfo(this.chartRawData.usage[this.chartRawData.usage.length - 1]);
          }
        },
        onHover: (event, elements) => {
          if (event.native && event.native.target) {
            event.native.target.style.cursor = elements.length > 0 ? 'pointer' : 'default';
          }
        }
      }
    });

    this.chartRawData = { usage: pageData };

    if (pageData.length > 0 && !this._selectedDate) {
      this._updateSelectedInfo(pageData[pageData.length - 1]);
    }
  }

  _updateChartData() {
    if (!this._chart) {
      this._createOrUpdateChart();
      return;
    }

    const entity = this._getEntity();
    if (!entity) return;

    const rawData = this._getRawData(entity);
    const { pageData, labels, usageData, barColors } = this._buildChartView(rawData);

    this._chart.data.labels = labels;
    this._chart.data.datasets[0].data = usageData;
    this._chart.data.datasets[0].backgroundColor = barColors;
    this._chart.data.datasets[0].borderColor = barColors;
    this._chart.update('none');

    this.chartRawData = { usage: pageData };

    if (pageData.length > 0 && !this._selectedDate) {
      this._updateSelectedInfo(pageData[pageData.length - 1]);
    }
    this.requestUpdate();
  }

  _updateSelectedInfo(selectedItem) {
    if (!selectedItem) return;
    const dateStr = selectedItem.invoice_to || selectedItem.date;
    const date = new Date(dateStr);
    const dateFormatted = this._formatDate(date, { month: 'long', year: 'numeric' });

    this._selectedDate = {
      date: dateStr,
      dateFormatted,
      cost: selectedItem.cost || 0,
      consumption: selectedItem.consumption || 0,
      is_estimated: selectedItem.is_estimated === true,
      rawItem: selectedItem
    };
    this.requestUpdate();
  }

  _handleNavigation(direction) {
    const entity = this._getEntity();
    if (!entity) return;

    const rawData = this._getRawData(entity);
    const maxPage = Math.ceil(rawData.length / this.itemsPerPage) - 1;

    if (direction === 'next' && this._currentPage > 0) {
      this._currentPage--;
      this._selectedDate = null;
      this._updateChartData();
    } else if (direction === 'prev' && maxPage > 0 && this._currentPage < maxPage) {
      // maxPage > 0 short-circuits single-page datasets so a programmatic
      // call (or a click that slipped past the disabled-arrow visibility
      // guard) cannot push _currentPage off the end into a blank window.
      this._currentPage++;
      this._selectedDate = null;
      this._updateChartData();
    }
  }

  _hasPreviousPageData() {
    const entity = this._getEntity();
    if (!entity) return false;
    const rawData = this._getRawData(entity);
    const nextPageStartIndex = (this._currentPage + 1) * this.itemsPerPage;
    return rawData.length > nextPageStartIndex;
  }

  _hasNextPageData() {
    return this._currentPage > 0;
  }

  _isNavDisabled(direction) {
    if (direction === 'prev') return !this._hasPreviousPageData();
    if (direction === 'next') return !this._hasNextPageData();
    return false;
  }

  // Format a billing period as "1 Feb 2026 - 27 Mar 2026\n&nbsp;", or null
  // when the entry doesn't have both invoice anchors (gas pipeline
  // guarantees snake_case via pymercury consumption_periods + the local
  // _collapse_gas_pairs fallback — no camelCase shape exists for gas).
  _formatInvoiceRange(item) {
    const from = item.invoice_from;
    const to = item.invoice_to;
    if (!from || !to) return null;
    const opts = { day: 'numeric', month: 'short', year: 'numeric' };
    const fromStr = new Date(from).toLocaleDateString('en-NZ', opts);
    const toStr = new Date(to).toLocaleDateString('en-NZ', opts);
    return `${fromStr} - ${toStr}\n&nbsp;`;
  }

  _getNavigationDescription() {
    const entity = this._getEntity();
    if (!entity) return 'No data available';

    try {
      if (this._selectedDate && this._selectedDate.rawItem) {
        const range = this._formatInvoiceRange(this._selectedDate.rawItem);
        if (range) return range;
      }

      const rawData = this._getRawData(entity);
      const { pageData } = this._getPaginatedData(rawData);
      if (pageData.length === 0) return 'No monthly gas data available';

      const latest = pageData[pageData.length - 1];
      const range = this._formatInvoiceRange(latest);
      if (range) return range;

      const dateStr = latest.invoice_to || latest.date;
      return `${new Date(dateStr).toLocaleDateString('en-NZ', { month: 'short', year: 'numeric' })}\n&nbsp;`;
    } catch (error) {
      console.error('Error generating navigation description:', error);
      return 'Data unavailable';
    }
  }

  _shouldShowNavigation(rawData) {
    return rawData.length > 0;
  }

  render() {
    const validationError = this._validateRenderConditions();
    if (validationError) return validationError;

    const entity = this._getEntity();
    if (!this._hasChartData()) {
      return this._renderLoadingState('Loading Gas Monthly Data...', '🔥');
    }
    return this._renderGasCard(entity);
  }

  _renderGasCard(entity) {
    const rawData = this._getRawData(entity);
    const showNavigation = this.config.show_navigation && this._shouldShowNavigation(rawData);

    return html`
      <ha-card class="mercury-chart-card">
        <div class="card-content">
          <div class="header">
            <div class="title-row">
              <h3>${this.config.name}</h3>
            </div>
          </div>

          ${showNavigation ? this._renderNavigation() : ''}

          <div class="chart-container">
            <canvas id="gasChart" width="400" height="200"></canvas>
          </div>

          ${this._renderCustomLegend()}

          <div class="chart-info ${this._selectedDate?.is_estimated ? 'estimate' : ''}">
            <div class="data-info">
              ${this._selectedDate ? html`
                <div class="usage-details">
                  <div class="usage-date">
                    <span class="fire-emoji">🔥</span>Your gas usage for this billing period
                  </div>
                  <div class="usage-stats">$${this._selectedDate.cost.toFixed(2)} | ${this._selectedDate.consumption.toFixed(2)} kWh</div>
                </div>
              ` : html`Loading...`}
            </div>
          </div>
        </div>
      </ha-card>
    `;
  }

  _renderNavigation() {
    const description = this._getNavigationDescription();
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
    // Inline `style` on the second swatch so cascade order can't lose. The
    // shared `.legend-circle` rule in styles.js sets yellow as the default,
    // and inline-style (specificity 1,0,0,0) beats anything in the cascade.
    // Label "Estimate" matches the Mercury app's terminology.
    return html`
      <div class="custom-legend">
        <div class="legend-item">
          <div class="legend-circle"></div>
          <span class="legend-label">Actual</span>
        </div>
        <div class="legend-item">
          <div class="legend-circle" style="background-color: #727272;"></div>
          <span class="legend-label">Estimate</span>
        </div>
      </div>
    `;
  }
}

if (!customElements.get('mercury-gas-monthly-summary-card')) {
  customElements.define('mercury-gas-monthly-summary-card', MercuryGasMonthlySummaryCard);
}

if (window.customCards) {
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: 'mercury-gas-monthly-summary-card',
    name: 'Mercury Gas Monthly Summary Card',
    description: 'Monthly gas consumption bar chart for Mercury Energy NZ (estimate vs actual)',
    preview: false,
    documentationURL: 'https://github.com/bkintanar/home-assistant-mercury-co-nz'
  });
}

console.info(
  '%c MERCURY-GAS-MONTHLY-SUMMARY-CARD %c v1.6.2 ',
  'color: orange; font-weight: bold; background: black',
  'color: white; font-weight: bold; background: dimgray'
);
