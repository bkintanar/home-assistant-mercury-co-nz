/* Mercury Energy LitElement Core Utilities
 * Shared functionality for all Mercury Energy LitElement cards
 * Used by: weekly-summary-card.js, monthly-summary-card.js, energy-usage-card.js
 */

// Mercury Energy LitElement Core - Common functionality for all LitElement cards
export const mercuryLitCore = {
  // ===== INITIALIZATION METHODS =====

  initializeBase() {
    // Common property initialization
    this._entity = null;
    this._chartLoaded = false;
    this._chart = null;
    this.chartLoadPromise = null;
    this.CHART_COLORS = {
      PRIMARY_YELLOW: 'rgb(255, 240, 0)',
      TEMPERATURE_BLUE: 'rgb(105, 162, 185)'
    };
  },

  // ===== CONFIGURATION METHODS =====

  setConfigBase(config, cardName = 'Mercury Energy Card') {
    if (!config) {
      throw new Error('Invalid configuration');
    }

    if (!config.entity) {
      throw new Error('Entity is required');
    }

    // Return base config with defaults
    return {
      name: cardName,
      entity: config.entity,
      show_header: config.show_header !== false,
      ...config
    };
  },

  // ===== ENTITY METHODS =====

  _getEntity() {
    if (!this.hass || !this.config?.entity) return null;
    return this.hass.states[this.config.entity];
  },

  _isEntityAvailable() {
    const entity = this._getEntity();
    return entity && entity.state !== 'unavailable' && entity.state !== 'unknown';
  },

  // ===== CHART.JS MANAGEMENT =====

  async _loadChartJS() {
    if (this._chartLoaded || window.Chart) {
      this._chartLoaded = true;
      return Promise.resolve();
    }

    // Return existing promise if already loading
    if (this.chartLoadPromise) {
      return this.chartLoadPromise;
    }

    this.chartLoadPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.5.0/dist/chart.umd.min.js';

      script.onload = () => {
        if (window.Chart) {
          this._chartLoaded = true;
          console.log('📊 Chart.js loaded successfully for Mercury Energy card');
          resolve();
        } else {
          reject(new Error('Chart.js loaded but not accessible'));
        }
      };

      script.onerror = () => {
        console.error('📊 Failed to load Chart.js');
        reject(new Error('Failed to load Chart.js'));
      };

      // Add timeout for loading
      setTimeout(() => {
        if (!this._chartLoaded) {
          script.remove();
          reject(new Error('Chart.js loading timeout'));
        }
      }, 10000); // 10 second timeout

      document.head.appendChild(script);
    });

    return this.chartLoadPromise;
  },

  // ===== VISIBILITY DETECTION =====

  _isCardVisible() {
    if (typeof document !== 'undefined' && document.hidden) return false;
    if (!this.isConnected) return false;

    const rect = this.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return false;

    // Check if element is actually visible (not just in DOM)
    const style = getComputedStyle(this);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
      return false;
    }

    return true;
  },

  _setupVisibilityObserver() {
    if ('IntersectionObserver' in window) {
      this._visibilityObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
          if (entry.isIntersecting && entry.target === this) {
            setTimeout(() => {
              if (this._isCardVisible() && this._chartLoaded && this._hasChartData && this._hasChartData() && !this._chart) {
                this._createOrUpdateChart();
              }
            }, 100);
          }
        });
      }, {
        threshold: 0.1,
        rootMargin: '10px'
      });
    }

    // Also listen for document visibility changes (tab switching)
    if (typeof document !== 'undefined') {
      this._handleVisibilityChange = () => {
        if (!document.hidden && this._isCardVisible() && this._chartLoaded && this._hasChartData && this._hasChartData() && !this._chart) {
          setTimeout(() => this._createOrUpdateChart(), 200);
        }
      };

      document.addEventListener('visibilitychange', this._handleVisibilityChange);
    }
  },

  // ===== LIFECYCLE HELPERS =====

  setupLifecycleBase() {
    // Common connectedCallback logic
    this._loadChartJS();
    this._detectDarkMode();

    // Start observing visibility
    if (this._visibilityObserver) {
      this._visibilityObserver.observe(this);
    }

    // Schedule chart creation check after connection
    setTimeout(() => {
      if (this._isCardVisible() && this._chartLoaded && this._hasChartData && this._hasChartData() && !this._chart) {
        this._createOrUpdateChart();
      }
    }, 100);
  },

  cleanupLifecycleBase() {
    // Common disconnectedCallback logic

    // Stop observing visibility
    if (this._visibilityObserver) {
      this._visibilityObserver.unobserve(this);
      this._visibilityObserver.disconnect();
      this._visibilityObserver = null;
    }

    // Remove visibility change listener
    if (this._handleVisibilityChange) {
      document.removeEventListener('visibilitychange', this._handleVisibilityChange);
      this._handleVisibilityChange = null;
    }

    // Destroy chart
    if (this._chart) {
      try {
        this._chart.destroy();
      } catch (error) {
        console.warn('📊 Error destroying chart:', error);
      }
      this._chart = null;
    }
  },

  handleFirstUpdatedBase() {
    // Common firstUpdated logic
    if (this._isCardVisible() && this._chartLoaded && this._hasChartData && this._hasChartData() && !this._chart) {
      this._createOrUpdateChart();
    }
  },

  handleUpdatedBase(changedProps) {
    // Common updated logic for chart management
    if (this._chartLoaded && this._hasChartData && this._hasChartData()) {
      // Wait for DOM to be ready
      setTimeout(() => {
        const canvas = this.shadowRoot?.querySelector('canvas');

        // If canvas exists but chart is missing, recreate it
        if (canvas && !this._chart && this._isCardVisible()) {
          this._createOrUpdateChart();
        }
        // If chart exists but canvas context is lost, recreate
        else if (this._chart && canvas) {
          try {
            const ctx = canvas.getContext('2d');
            if (!ctx || ctx.isPointInPath === undefined) {
              console.log('📊 Canvas context lost, recreating chart');
              this._chart.destroy();
              this._chart = null;
              this._createOrUpdateChart();
              return;
            }
          } catch (error) {
            console.log('📊 Canvas context check failed, recreating chart');
            this._chart.destroy();
            this._chart = null;
            this._createOrUpdateChart();
            return;
          }
        }

        // Handle entity changes
        const entity = this._getEntity();
        if (entity && changedProps.has('hass')) {
          const oldHass = changedProps.get('hass');
          const oldEntity = oldHass?.states[this.config?.entity];
          const newEntity = entity;

          // Check if entity data actually changed
          const entityChanged = !oldEntity ||
            JSON.stringify(oldEntity.attributes) !== JSON.stringify(newEntity.attributes) ||
            oldEntity.state !== newEntity.state;

          // Only create/update chart if data actually changed and we have valid data
          if (this._isCardVisible() && this._chartLoaded && this._hasChartData && this._hasChartData() && entityChanged) {
            // Use setTimeout to ensure DOM is ready
            setTimeout(() => {
              if (this._updateChartData) {
                this._updateChartData();
              } else {
                this._createOrUpdateChart();
              }
            }, 0);
          }
        }
      }, 50);
    }
  },

  // ===== UTILITY METHODS =====

  _formatDate(dateString, options = {}) {
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
      console.warn('Mercury Energy: Date formatting error:', error);
      return typeof dateString === 'string' ? dateString : '';
    }
  },

  _detectDarkMode() {
    // Method 1: Check Home Assistant theme
    const haMain = document.querySelector('ha-main') || document.querySelector('home-assistant-main');
    if (haMain) {
      const computedStyle = getComputedStyle(haMain);
      const bgColor = computedStyle.backgroundColor;
      if (bgColor) {
        const rgbMatch = bgColor.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
        if (rgbMatch) {
          const r = parseInt(rgbMatch[1]);
          const g = parseInt(rgbMatch[2]);
          const b = parseInt(rgbMatch[3]);
          const brightness = (r * 299 + g * 587 + b * 114) / 1000;
          return brightness < 128;
        }
      }
    }

    // Method 2: Check system preference
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
      return true;
    }

    // Default to light mode
    return false;
  },

  // ===== STANDARD METHODS =====

  getCardSize(size = 6) {
    return size;
  },

  // ===== ERROR STATE METHODS =====

  _renderConfigNeededState() {
    return `
      <ha-card>
        <div style="padding: 20px; text-align: center;">
          <div style="margin-bottom: 10px;">⚙️ Configuration Required</div>
          <div style="font-size: 0.8em; opacity: 0.7; margin-bottom: 15px;">Please configure an entity for this Mercury Energy card</div>
          <div style="font-size: 0.7em; background: var(--secondary-background-color, #f5f5f5); padding: 10px; border-radius: 4px; text-align: left;">
            <strong>Example configuration:</strong><br/>
            type: custom:mercury-energy-card<br/>
            entity: sensor.mercury_nz_energy_usage
          </div>
        </div>
      </ha-card>
    `;
  },

  _renderEntityUnavailableState() {
    return `
      <ha-card>
        <div style="padding: 20px; text-align: center;">
          <div style="margin-bottom: 10px;">⚠️ Entity Unavailable</div>
          <div style="font-size: 0.8em; opacity: 0.7;">Mercury Energy entity is not available</div>
          <div style="font-size: 0.7em; margin-top: 10px; opacity: 0.7;">Entity: ${this.config?.entity || 'Unknown'}</div>
        </div>
      </ha-card>
    `;
  },

  _renderLoadingState() {
    return `
      <ha-card>
        <div style="padding: 20px; text-align: center;">
          <div style="margin-bottom: 10px;">📊 Loading...</div>
          <div style="font-size: 0.8em; opacity: 0.7;">Mercury Energy data is being loaded</div>
        </div>
      </ha-card>
    `;
  }
};

console.info(
  '%c MERCURY-LIT-CORE %c v1.0.0 ',
  'color: orange; font-weight: bold; background: black',
  'color: white; font-weight: bold; background: dimgray'
);
