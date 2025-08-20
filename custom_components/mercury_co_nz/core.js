/* Mercury Energy LitElement Core Utilities
 * Shared functionality for all Mercury Energy LitElement cards
 * Used by: weekly-summary-card.js, monthly-summary-card.js, energy-usage-card.js
 */

import { html } from 'https://unpkg.com/lit@3.1.0/index.js?module';

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

  // Get theme color with fallbacks (used by chart cards for styling)
  _getThemeColor(cssVar, alpha = 1) {
    let color = '';
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

    if (!color) {
      // Fallback colors based on dark/light mode detection
      const isDarkMode = this._detectDarkMode();
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

    // Handle different color formats and alpha
    if (color.startsWith('#')) {
      return alpha === 1 ? color : this._hexToRgba(color, alpha);
    } else if (color.startsWith('rgb')) {
      if (alpha === 1) return color;
      // Convert rgb to rgba
      const rgbMatch = color.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
      if (rgbMatch) {
        return `rgba(${rgbMatch[1]}, ${rgbMatch[2]}, ${rgbMatch[3]}, ${alpha})`;
      }
    }

    return color || (this._detectDarkMode() ? '#e1e1e1' : '#212121');
  },

  // Convert hex to rgba
  _hexToRgba(hex, alpha = 1) {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  },

  // Apply theme-specific adjustments to card
  _applyThemeAdjustments() {
    this.updateComplete.then(() => {
      const card = this.shadowRoot.querySelector('ha-card');
      if (!card) return;

      const isDark = this._detectDarkMode();

      if (isDark) {
        this.setAttribute('dark-mode', '');
        card.setAttribute('data-dark-mode', 'true');
      } else {
        this.removeAttribute('dark-mode');
        card.removeAttribute('data-dark-mode');
      }
    });
  },

  // ===== STANDARD METHODS =====

  getCardSize(size = 6) {
    return size;
  },

  // ===== RENDER VALIDATION METHODS =====

  // Common render validation that all cards need
  _validateRenderConditions() {
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

    // All validations passed - return null to indicate success
    return null;
  },

  // ===== ERROR STATE METHODS =====

  // Helper method to generate configuration data for render methods
  _getConfigNeededStateData() {
    // Determine card type and element name from config
    const cardName = this.config?.name || 'Mercury Energy Card';
    let elementType = 'mercury-energy-card';
    let description = 'Please configure an entity for this Mercury Energy card';

    // Dynamic card type detection based on config name
    if (cardName.toLowerCase().includes('monthly')) {
      elementType = 'mercury-energy-monthly-summary-card';
      description = 'Please configure an entity for this Mercury Energy monthly summary';
    } else if (cardName.toLowerCase().includes('weekly')) {
      elementType = 'mercury-energy-weekly-summary-card';
      description = 'Please configure an entity for this Mercury Energy weekly summary';
    } else if (cardName.toLowerCase().includes('usage')) {
      elementType = 'mercury-energy-usage-card';
      description = 'Please configure an entity for this Mercury Energy usage chart';
    }

    return {
      elementType,
      description,
      cardName
    };
  },

  // Render configuration needed state with HTML template
  _renderConfigNeededState() {
    const { elementType, description } = this._getConfigNeededStateData();

    return html`
      <ha-card>
        <div class="loading-state">
          <div class="loading-message">⚙️ Configuration Required</div>
          <div class="loading-description" style="margin-bottom: 15px;">${description}</div>
          <div style="font-size: 0.7em; background: var(--secondary-background-color, #f5f5f5); padding: 10px; border-radius: 4px; text-align: left;">
            <strong>Example configuration:</strong><br/>
            type: custom:${elementType}<br/>
            entity: sensor.mercury_nz_energy_usage
          </div>
        </div>
      </ha-card>
    `;
  },

  _renderEntityUnavailableState() {
    return html`
      <ha-card>
        <div style="padding: 20px; text-align: center;">
          <div style="margin-bottom: 10px;">⚠️ Entity Unavailable</div>
          <div style="font-size: 0.8em; opacity: 0.7;">Mercury Energy entity is not available</div>
          <div style="font-size: 0.7em; margin-top: 10px; opacity: 0.7;">Entity: ${this.config?.entity || 'Unknown'}</div>
        </div>
      </ha-card>
    `;
  },

  _renderLoadingState(message = 'Loading...', icon = '📊', description = null) {
    // Generate card-specific description if not provided
    if (!description) {
      const cardName = this.config?.name || 'Mercury Energy Card';
      if (cardName.toLowerCase().includes('monthly')) {
        description = 'Mercury Energy monthly data is loading';
      } else if (cardName.toLowerCase().includes('weekly')) {
        description = 'Mercury Energy weekly data is loading';
      } else if (cardName.toLowerCase().includes('usage')) {
        description = 'Mercury Energy chart data is loading';
      } else {
        description = 'Mercury Energy data is loading';
      }
    }

    return html`
      <ha-card>
        <div class="loading-state">
          <div class="loading-message">${icon} ${message}</div>
          <div class="loading-description">${description}</div>
        </div>
      </ha-card>
    `;
  }
};

console.info(
  '%c MERCURY-CORE %c v1.0.0 ',
  'color: orange; font-weight: bold; background: black',
  'color: white; font-weight: bold; background: dimgray'
);
