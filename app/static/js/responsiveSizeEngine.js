/**
 * responsiveSizeEngine.js
 * 
 * Part of the Automatic Content-Aware Footer Layout Engine for Iimagica.
 * Implements the mathematical sizing formula:
 * H_f = P_t + P_b + Sum(H_r) + Sum(G_r)
 * 
 * Dynamically calculates footer height, row heights, padding, and
 * proportional image dimensions while enforcing maximum allowable limits.
 */

(function (root, factory) {
  if (typeof define === 'function' && define.amd) {
    define([], factory);
  } else if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.ResponsiveSizeEngine = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // Sizing constraints
  const CONFIG = {
    minFooterHeight: 85,
    maxFooterRatio: 0.28,        // Max 28% of total poster height
    defaultPaddingBottom: 14,
    minPaddingBottom: 8,
    minRowGap: 5,
    normalRowGap: 9,
    generousRowGap: 14
  };

  /**
   * Determine minimum top clearance based on the geometry of the selected footer shape.
   * e.g. Curved arch or Wave cuts dip into the footer, so text needs higher clearance.
   */
  function getShapeTopPadding(shape) {
    switch (shape) {
      case 'curved':
        return 26;
      case 'wave':
        return 22;
      case 'double':
        return 24;
      case 'diagonal':
        return 22;
      case 'rounded':
        return 16;
      case 'rectangle':
      default:
        return 14;
    }
  }

  /**
   * Calculate exact row height requirements from row elements
   */
  function calculateRowHeight(rowElements) {
    if (!rowElements || rowElements.length === 0) return 0;
    let maxItemHeight = 0;
    for (let el of rowElements) {
      const h = el.height || el.fontSize * 1.3 || 18;
      if (h > maxItemHeight) maxItemHeight = h;
    }
    return Math.ceil(maxItemHeight);
  }

  /**
   * Main Sizing Calculator implementing H_f = P_t + P_b + Sum(H_r) + Sum(G_r)
   * 
   * @param {Object} params
   * @param {number} params.posterWidth - Full poster canvas width (e.g. 1080)
   * @param {number} params.posterHeight - Full poster canvas height (e.g. 1350)
   * @param {string} params.footerShape - 'wave', 'curved', 'rectangle', etc.
   * @param {Array<Array>} params.rows - Array of rows, each containing element definitions
   * @param {Object} params.analysis - Content analysis profile from ContentAnalysisEngine
   * @param {Object} params.options - Overrides (e.g. compression mode, custom padding)
   */
  function calculateDimensions(params) {
    const {
      posterWidth = 1080,
      posterHeight = 1350,
      footerShape = 'wave',
      rows = [],
      analysis = {},
      options = {}
    } = params;

    const maxAllowableHeight = Math.round(posterHeight * (options.maxFooterRatio || CONFIG.maxFooterRatio));
    const basePaddingTop = getShapeTopPadding(footerShape);
    let pt = Math.round(basePaddingTop * (options.paddingScale || 1.0));
    let pb = Math.round(CONFIG.defaultPaddingBottom * (options.paddingScale || 1.0));
    let rowGap = options.rowGap !== undefined ? options.rowGap : CONFIG.normalRowGap;

    // Calculate individual row heights
    const rowHeights = rows.map(row => calculateRowHeight(row));
    const sumRowHeights = rowHeights.reduce((a, b) => a + b, 0);
    const sumGaps = Math.max(0, rows.length - 1) * rowGap;

    // Sizing Formula: H_f = P_t + P_b + Sum(H_r) + Sum(G_r)
    let footerHeight = pt + pb + sumRowHeights + sumGaps;

    let isCompressed = false;
    let overflowWarning = null;

    // If calculated height exceeds maximum, apply multi-stage compression
    if (footerHeight > maxAllowableHeight) {
      isCompressed = true;

      // 1. Compress gaps
      rowGap = Math.max(CONFIG.minRowGap, Math.round(rowGap * 0.7));
      // 2. Compress padding
      pt = Math.max(Math.round(basePaddingTop * 0.8), pt - 6);
      pb = Math.max(CONFIG.minPaddingBottom, pb - 4);

      footerHeight = pt + pb + sumRowHeights + (Math.max(0, rows.length - 1) * rowGap);

      // If still overflowing allowable limit, cap and flag warning
      if (footerHeight > maxAllowableHeight) {
        footerHeight = maxAllowableHeight;
        overflowWarning = {
          message: 'Content volume is high. Footer height reached maximum allowed area.',
          exceededBy: (pt + pb + sumRowHeights + sumGaps) - maxAllowableHeight
        };
      }
    }

    // Ensure it doesn't fall below minimal comfortable height
    footerHeight = Math.max(CONFIG.minFooterHeight, footerHeight);

    // Dynamic Image Dimension Sizing (preserving aspect ratio)
    let logoSize = { width: 0, height: 0 };
    if (analysis.logo && analysis.logo.exists) {
      const targetLogoH = Math.min(56, Math.max(34, Math.round(footerHeight * 0.36)));
      const targetLogoW = Math.round(targetLogoH * analysis.logo.aspectRatio);
      logoSize = {
        width: Math.min(95, targetLogoW),
        height: targetLogoH
      };
    }

    let photoSize = { width: 0, height: 0 };
    if (analysis.photo && analysis.photo.exists) {
      // Photo badge can take up to 60-70% of available footer height
      const targetPhotoH = Math.min(115, Math.max(50, Math.round(footerHeight * 0.68)));
      const targetPhotoW = Math.round(targetPhotoH * analysis.photo.aspectRatio);
      photoSize = {
        width: targetPhotoW,
        height: targetPhotoH
      };
    }

    return {
      footerHeight: Math.round(footerHeight),
      paddingTop: pt,
      paddingBottom: pb,
      rowGap,
      rowHeights,
      sumRowHeights,
      logoSize,
      photoSize,
      isCompressed,
      maxAllowableHeight,
      overflowWarning
    };
  }

  return {
    CONFIG,
    getShapeTopPadding,
    calculateRowHeight,
    calculateDimensions
  };
}));
