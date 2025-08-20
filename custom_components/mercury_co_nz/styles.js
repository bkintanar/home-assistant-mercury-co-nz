// Mercury Energy Cards - Shared LitElement Styles
// Reusable CSS styles for all Mercury Energy LitElement cards
// Used by: weekly-summary-card-lit.js, future LitElement cards

import { css } from 'https://unpkg.com/lit@3.1.0/index.js?module';

// Base card styles - common to all Mercury Energy LitElement cards
export const baseCardStyles = css`
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
    padding: 16px;
  }

  /* Header styles */
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

  /* Loading states */
  .loading-state {
    padding: 20px;
    text-align: center;
  }

  .loading-message {
    margin-bottom: 10px;
    font-size: 16px;
  }

  .loading-description {
    font-size: 0.8em;
    opacity: 0.7;
  }

  /* Responsive design */
  @media (max-width: 480px) {
    /* Card content padding is already 16px by default */
  }
`;

// Usage summary styles - for cost display sections
export const usageSummaryStyles = css`
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

  .consumption {
    font-size: 18px;
    font-weight: 500;
    color: var(--primary-text-color);
    line-height: 1;
  }

  .asterisk {
    font-size: 28px;
    color: var(--secondary-text-color);
    margin-left: 2px;
    vertical-align: top;
  }

  /* Responsive cost display */
  @media (max-width: 480px) {
    .cost {
      font-size: 36px;
    }

    .consumption {
      font-size: 16px;
    }
  }
`;

// Period info styles - for date ranges and period display
export const periodInfoStyles = css`
  .period-info {
    margin-bottom: 16px;
    font-size: 14px;
  }

  .period-dates {
    color: var(--primary-text-color);
    font-weight: 500;
    font-size: 18px;
    line-height: 1;
  }

  .days-remaining {
    color: var(--primary-text-color);
    font-weight: 500;
  }

  /* Period info with flex layout (for cards that need side-by-side layout) */
  .period-info.flex-layout {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  /* Responsive period info */
  @media (max-width: 480px) {
    .period-info.flex-layout {
      flex-direction: column;
      gap: 8px;
      align-items: flex-start;
    }

    .period-dates {
      font-size: 16px;
    }
  }
`;

// Notes styles - for weekly/monthly notes sections
export const notesStyles = css`
  .weekly-notes,
  .monthly-notes,
  .notes {
    margin-bottom: 16px;
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

  .footer-notes {
    font-size: 12px;
    color: var(--secondary-text-color);
    line-height: 1.4;
  }

  .footer-notes .note {
    margin-bottom: 8px;
    font-size: 12px;
    color: var(--secondary-text-color);
  }

  /* Dark mode notes */
  ha-card[data-dark-mode="true"] .weekly-notes,
  ha-card[data-dark-mode="true"] .monthly-notes,
  ha-card[data-dark-mode="true"] .notes,
  ha-card[data-theme*="dark"] .weekly-notes,
  ha-card[data-theme*="dark"] .monthly-notes,
  ha-card[data-theme*="dark"] .notes,
  :host([dark-mode]) .weekly-notes,
  :host([dark-mode]) .monthly-notes,
  :host([dark-mode]) .notes {
    background: var(--card-background-color, #1e1e1e);
    border: 1px solid var(--divider-color, #3d3d3d);
  }
`;

// Chart styles - for Chart.js containers and chart info
export const chartStyles = css`
  .chart-container {
    height: 200px;
    margin-bottom: 20px;
    background: var(--card-background-color, white);
    border-radius: 8px;
    padding: 16px;
    border: 1px solid var(--divider-color);
  }

  /* Chart canvas sizing */
  .chart-container canvas {
    width: 100% !important;
    height: 100% !important;
  }

  /* Chart info section - yellow highlight box */
  .chart-info {
    text-align: left;
    margin-top: 12px;
    padding: 12px;
    background: rgb(255, 240, 0); /* PRIMARY_YELLOW */
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
    margin-bottom: 4px;
  }

  .usage-stats {
    font-size: 14px;
    color: black;
  }

  /* Dark mode chart container */
  ha-card[data-dark-mode="true"] .chart-container,
  ha-card[data-theme*="dark"] .chart-container,
  :host([dark-mode]) .chart-container {
    background: var(--card-background-color, #1e1e1e);
    border: 1px solid var(--divider-color, #3d3d3d);
  }

  /* Responsive chart */
  @media (max-width: 480px) {
    .chart-container {
      height: 160px;
      padding: 12px;
    }
  }
`;

// Progress bar styles - for billing period progress
export const progressBarStyles = css`
  .progress-container {
    margin-bottom: 4px;
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

  .progress-label {
    display: flex;
    justify-content: space-between;
    margin-bottom: 8px;
    font-size: 14px;
  }

  /* Dark mode progress bar */
  ha-card[data-dark-mode="true"] .progress-bar,
  ha-card[data-theme*="dark"] .progress-bar,
  :host([dark-mode]) .progress-bar {
    background-color: var(--card-background-color, #2d2d2d);
    border: 1px solid var(--divider-color, #3d3d3d);
  }
`;

// Projected bill styles - for monthly summary projected bills
export const projectedBillStyles = css`
  .projected-bill {
    background: var(--card-background-color, var(--ha-card-background, #fafafa));
    border: 1px solid var(--divider-color);
    border-radius: 8px;
    padding: 12px;
    margin-bottom: 16px;
  }

  .projected-content {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 14px;
    color: var(--primary-text-color);
    font-weight: 500;
  }

  .plug-icon {
    font-size: 16px;
  }

  /* Ensure projected bill text is always visible */
  .projected-bill span {
    color: var(--primary-text-color) !important;
  }

  /* Dark mode projected bill */
  ha-card[data-dark-mode="true"] .projected-bill,
  ha-card[data-theme*="dark"] .projected-bill,
  :host([dark-mode]) .projected-bill {
    background: var(--card-background-color, #1e1e1e);
    border: 1px solid var(--divider-color, #3d3d3d);
  }

  /* Dark mode text enhancement */
  ha-card[data-dark-mode="true"] .projected-bill span,
  ha-card[data-theme*="dark"] .projected-bill span,
  :host([dark-mode]) .projected-bill span {
    color: var(--primary-text-color, #ffffff) !important;
  }
`;

// Time period selector styles - for chart period switching
export const timePeriodStyles = css`
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
    background: rgb(255, 240, 0); /* PRIMARY_YELLOW */
    color: #000;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
  }

  .period-btn:hover:not(.active) {
    background: var(--primary-color);
    color: white;
  }

  /* Responsive period selector */
  @media (max-width: 480px) {
    .time-period-selector {
      margin-bottom: 12px;
    }

    .period-btn {
      padding: 8px 12px;
      font-size: 12px;
    }
  }
`;

// Navigation styles - for chart navigation controls
export const navigationStyles = css`
  .navigation {
    display: flex;
    justify-content: center;
    align-items: center;
    margin-bottom: 16px;
  }

  .nav-info {
    font-weight: 500;
    color: var(--primary-text-color);
  }

  .nav-date-container {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: start;
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

  .nav-date {
    text-align: center;
    line-height: 1.3;
    display: block;
    word-break: keep-all;
    hyphens: none;
    min-width: 0;
    padding: 0 4px;
  }

  /* Responsive navigation */
  @media (max-width: 480px) {
    .navigation {
      gap: 8px;
    }

    .nav-btn {
      padding: 6px 10px;
      font-size: 11px;
    }
  }
`;

// Chart legend styles - for custom chart legends
export const chartLegendStyles = css`
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
    background-color: rgb(255, 240, 0); /* PRIMARY_YELLOW */
    border: 1px solid rgba(0, 0, 0, 0.1);
  }

  .legend-line {
    width: 24px;
    height: 2px;
    background: rgb(105, 162, 185); /* TEMPERATURE_BLUE */
    border: 1px solid rgba(0, 0, 0, 0.1);
    border-radius: 1px;
  }

  .legend-label {
    font-size: 12px;
    color: var(--primary-text-color);
    font-weight: 500;
  }
`;

// Enhanced chart styles - builds on the basic chartStyles with additional features
export const enhancedChartStyles = css`
  ${chartStyles}

  /* Chart specific canvas sizing */
  #energyChart {
    width: 100% !important;
    height: 100% !important;
  }

  /* Enhanced chart container for energy usage charts */
  .chart-container {
    background: var(--card-background-color, white);
    border-radius: 4px;
    padding: 10px;
    position: relative;
    border: 1px solid var(--divider-color);
    height: 400px;
    border: none; /* Chart card specific override */
  }

  /* Chart card specific padding override */
  ha-card {
    padding: 0;
  }

  /* Card header styles */
  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .card-header h3 {
    margin: 0;
    color: var(--primary-text-color);
    font-size: 18px;
    font-weight: 600;
    letter-spacing: -0.5px;
  }

  /* Enhanced responsive chart */
  @media (max-width: 480px) {
    .chart-container {
      padding: 12px;
    }
  }
`;

// Combined styles - convenience export for cards that need everything
export const mercuryCardStyles = css`
  ${baseCardStyles}
  ${usageSummaryStyles}
  ${periodInfoStyles}
  ${notesStyles}
  ${chartStyles}
  ${progressBarStyles}
  ${projectedBillStyles}
`;

// Combined chart styles - convenience export for chart cards
export const mercuryChartStyles = css`
  ${baseCardStyles}
  ${usageSummaryStyles}
  ${periodInfoStyles}
  ${enhancedChartStyles}
  ${timePeriodStyles}
  ${navigationStyles}
  ${chartLegendStyles}
  ${notesStyles}
`;

// Mercury Energy brand colors
export const mercuryColors = {
  PRIMARY_YELLOW: 'rgb(255, 240, 0)',
  PRIMARY_YELLOW_ALPHA: 'rgba(255, 240, 0, 0.3)',
  SECONDARY_GRAY: '#727272',
  DARK_BACKGROUND: '#1e1e1e',
  DARK_BORDER: '#3d3d3d',
  TEMPERATURE_BLUE: 'rgb(105, 162, 185)'
};
