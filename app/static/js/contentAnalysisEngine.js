/**
 * contentAnalysisEngine.js
 * 
 * Part of the Automatic Content-Aware Footer Layout Engine for Iimagica.
 * Measures text and image dimensions, calculates space requirements,
 * checks line wrapping, and ensures aspect ratios are never distorted.
 */

(function (root, factory) {
  if (typeof define === 'function' && define.amd) {
    define([], factory);
  } else if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.ContentAnalysisEngine = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // Dedicated offscreen measurement canvas
  let _measureCanvas = null;
  let _measureCtx = null;

  function getContext() {
    if (!_measureCtx) {
      _measureCanvas = (typeof document !== 'undefined') ? document.createElement('canvas') : null;
      if (_measureCanvas) {
        _measureCanvas.width = 100;
        _measureCanvas.height = 100;
        _measureCtx = _measureCanvas.getContext('2d');
      }
    }
    return _measureCtx;
  }

  /**
   * Measure single-line text width in pixels using Canvas API
   */
  function measureTextWidth(text, font, size, weight = 'normal') {
    if (!text || text.length === 0) return 0;
    const ctx = getContext();
    if (!ctx) {
      // Fallback estimate if running without canvas
      return text.length * size * 0.58;
    }
    ctx.font = `${weight} ${size}px ${font}`;
    return ctx.measureText(text).width;
  }

  /**
   * Intelligently wrap text into multiple lines given a maximum container width.
   * Returns array of lines, max line width, and computed vertical height.
   */
  function wrapText(text, maxWidth, font, size, weight = 'normal', lineHeightFactor = 1.28) {
    if (!text || text.trim().length === 0) {
      return { lines: [], maxLineWidth: 0, totalHeight: 0, lineHeight: size * lineHeightFactor };
    }

    const words = text.trim().split(/\s+/);
    const lines = [];
    let currentLine = '';
    const lineHeight = Math.round(size * lineHeightFactor);

    for (let i = 0; i < words.length; i++) {
      const word = words[i];
      const testLine = currentLine.length === 0 ? word : currentLine + ' ' + word;
      const testWidth = measureTextWidth(testLine, font, size, weight);

      if (testWidth <= maxWidth || currentLine.length === 0) {
        currentLine = testLine;
      } else {
        lines.push(currentLine);
        currentLine = word;
      }
    }

    if (currentLine.length > 0) {
      lines.push(currentLine);
    }

    let maxLineWidth = 0;
    lines.forEach(line => {
      const w = measureTextWidth(line, font, size, weight);
      if (w > maxLineWidth) maxLineWidth = w;
    });

    return {
      lines,
      maxLineWidth,
      totalHeight: lines.length * lineHeight,
      lineHeight
    };
  }

  /**
   * Analyze an image object (logo or person photograph).
   * Reads intrinsic dimensions and calculates proportional scaled size without distortion.
   */
  function analyzeImage(img, maxAllowedW, maxAllowedH) {
    if (!img) {
      return { exists: false, width: 0, height: 0, aspectRatio: 1, naturalWidth: 0, naturalHeight: 0 };
    }

    const naturalWidth = img.naturalWidth || img.width || 100;
    const naturalHeight = img.naturalHeight || img.height || 100;
    const aspectRatio = naturalWidth / Math.max(1, naturalHeight);

    let scaledW = maxAllowedW;
    let scaledH = Math.round(scaledW / aspectRatio);

    if (scaledH > maxAllowedH) {
      scaledH = maxAllowedH;
      scaledW = Math.round(scaledH * aspectRatio);
    }

    return {
      exists: true,
      naturalWidth,
      naturalHeight,
      aspectRatio,
      isPortrait: aspectRatio < 0.9,
      isLandscape: aspectRatio > 1.15,
      isSquare: aspectRatio >= 0.9 && aspectRatio <= 1.15,
      width: Math.max(16, scaledW),
      height: Math.max(16, scaledH)
    };
  }

  /**
   * Comprehensive content profiler.
   * Takes all brand and contact fields and computes the exact volumetric requirements.
   */
  function analyzeContent(data, posterW, posterH, fontConfig = {}) {
    const primaryFont = fontConfig.primaryFont || "'Plus Jakarta Sans', sans-serif";
    const titleFont = fontConfig.titleFont || primaryFont;

    const brandName = (data.brandName || '').trim();
    const personName = (data.personName || '').trim();
    const personRole = (data.personRole || '').trim();
    const tagline = (data.tagline || data.cta || '').trim();

    // Collect valid contact items
    const rawContacts = Array.isArray(data.contacts) ? data.contacts : [];
    const contacts = rawContacts
      .map(c => {
        if (typeof c === 'string') return { label: '', value: c.trim(), type: 'custom' };
        return { label: c.label || '', value: (c.value || '').trim(), type: c.type || 'custom', icon: c.icon || '' };
      })
      .filter(c => c.value && c.value.length > 0);

    // Analyze Images
    const logoAnalysis = analyzeImage(data.logoImage, 70, 70);
    const photoAnalysis = analyzeImage(data.personPhoto, 95, 115);

    // Text metric scales
    const scales = {
      brand: { font: titleFont, size: 22, weight: '800' },
      personName: { font: primaryFont, size: 17, weight: '700' },
      personRole: { font: primaryFont, size: 12.5, weight: '600' },
      tagline: { font: primaryFont, size: 14.5, weight: '600' },
      contact: { font: primaryFont, size: 13, weight: '600' }
    };

    const brandMetrics = {
      text: brandName,
      width: measureTextWidth(brandName, scales.brand.font, scales.brand.size, scales.brand.weight),
      size: scales.brand.size
    };

    const personMetrics = {
      name: personName,
      nameWidth: measureTextWidth(personName, scales.personName.font, scales.personName.size, scales.personName.weight),
      role: personRole,
      roleWidth: measureTextWidth(personRole, scales.personRole.font, scales.personRole.size, scales.personRole.weight),
      combinedWidth: measureTextWidth(personName + (personRole ? ' • ' + personRole : ''), scales.personName.font, scales.personName.size, scales.personName.weight)
    };

    const taglineMetrics = {
      text: tagline,
      width: measureTextWidth(tagline, scales.tagline.font, scales.tagline.size, scales.tagline.weight),
      size: scales.tagline.size
    };

    const contactMetrics = contacts.map(c => {
      const displayText = c.label ? `${c.label}: ${c.value}` : c.value;
      return {
        ...c,
        displayText,
        width: measureTextWidth(displayText, scales.contact.font, scales.contact.size, scales.contact.weight) + (c.icon ? 20 : 0)
      };
    });

    const totalContactWidth = contactMetrics.reduce((sum, c) => sum + c.width, 0);

    // Compute Complexity / Volume Score
    let volumeScore = 0;
    if (brandName) volumeScore += 1.5;
    if (personName) volumeScore += 2.0;
    if (personRole) volumeScore += 1.0;
    if (tagline) volumeScore += 1.2;
    volumeScore += contacts.length * 1.0;
    if (logoAnalysis.exists) volumeScore += 1.5;
    if (photoAnalysis.exists) volumeScore += 2.5;

    let contentTier = 'small';
    if (volumeScore >= 7.5 || contacts.length >= 4 || (photoAnalysis.exists && contacts.length >= 2)) {
      contentTier = 'large';
    } else if (volumeScore >= 4.0 || contacts.length >= 2 || photoAnalysis.exists) {
      contentTier = 'medium';
    }

    return {
      brand: brandMetrics,
      person: personMetrics,
      tagline: taglineMetrics,
      contacts: contactMetrics,
      totalContactWidth,
      logo: logoAnalysis,
      photo: photoAnalysis,
      scales,
      volumeScore,
      contentTier,
      hasLogo: logoAnalysis.exists,
      hasPhoto: photoAnalysis.exists,
      hasBrand: brandName.length > 0,
      hasPerson: personName.length > 0,
      hasTagline: tagline.length > 0,
      hasContacts: contactMetrics.length > 0
    };
  }

  return {
    measureTextWidth,
    wrapText,
    analyzeImage,
    analyzeContent
  };
}));
