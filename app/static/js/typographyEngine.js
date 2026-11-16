/**
 * typographyEngine.js
 * 
 * Advanced Typography & Font Customization System for Iimagica.
 * Provides multi-role font management, category presets (modern, professional,
 * bold, elegant, traditional, decorative), letter-spacing, line-spacing,
 * text alignment, vertical positioning, and auto-font selection based on
 * logo, brand identity, and footer design.
 */

(function (root, factory) {
  if (typeof define === 'function' && define.amd) {
    define([], factory);
  } else if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.TypographyEngine = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // Comprehensive Font Catalog categorized by design archetype
  const FONT_CATALOG = {
    modern: [
      { id: 'plus_jakarta', name: 'Plus Jakarta Sans', family: "'Plus Jakarta Sans', sans-serif", weights: [400, 500, 600, 700, 800], bestFor: ['brand', 'heading', 'contact'] },
      { id: 'inter', name: 'Inter', family: "'Inter', sans-serif", weights: [400, 500, 600, 700], bestFor: ['contact', 'description'] },
      { id: 'montserrat', name: 'Montserrat', family: "'Montserrat', sans-serif", weights: [500, 600, 700, 800], bestFor: ['brand', 'heading'] }
    ],
    professional: [
      { id: 'roboto', name: 'Roboto', family: "'Roboto', sans-serif", weights: [400, 500, 700], bestFor: ['contact', 'description', 'brand'] },
      { id: 'open_sans', name: 'Open Sans', family: "'Open Sans', sans-serif", weights: [400, 600, 700], bestFor: ['contact', 'description'] }
    ],
    bold: [
      { id: 'oswald', name: 'Oswald', family: "'Oswald', sans-serif", weights: [500, 600, 700], bestFor: ['brand', 'heading'] },
      { id: 'bebas_neue', name: 'Bebas Neue', family: "'Bebas Neue', cursive", weights: [400], bestFor: ['brand', 'heading'] }
    ],
    elegant: [
      { id: 'playfair', name: 'Playfair Display', family: "'Playfair Display', serif", weights: [600, 700, 800], bestFor: ['brand', 'heading'] },
      { id: 'cormorant', name: 'Cormorant Garamond', family: "'Cormorant Garamond', serif", weights: [600, 700], bestFor: ['heading', 'description'] },
      { id: 'cinzel', name: 'Cinzel', family: "'Cinzel', serif", weights: [600, 700, 800], bestFor: ['brand', 'heading'] }
    ],
    traditional: [
      { id: 'merriweather', name: 'Merriweather', family: "'Merriweather', serif", weights: [400, 700], bestFor: ['brand', 'contact'] },
      { id: 'noto_serif_devanagari', name: 'Noto Serif Devanagari', family: "'Noto Serif Devanagari', serif", weights: [600, 700], bestFor: ['brand', 'heading', 'contact'] }
    ],
    decorative: [
      { id: 'great_vibes', name: 'Great Vibes', family: "'Great Vibes', cursive", weights: [400], bestFor: ['heading'] },
      { id: 'cinzel_dec', name: 'Cinzel Decorative', family: "'Cinzel', serif", weights: [700], bestFor: ['brand'] }
    ]
  };

  // Helper map for quick family lookup
  const ALL_FONTS = [];
  Object.keys(FONT_CATALOG).forEach(cat => {
    FONT_CATALOG[cat].forEach(f => ALL_FONTS.push({ ...f, category: cat }));
  });

  // Automated Typography Pairing Presets for Footer Designs
  const STYLE_PAIRINGS = {
    corporate: {
      brand: { family: "'Montserrat', sans-serif", weight: '700', style: 'normal', letterSpacing: 1.5, align: 'left', offsetY: 0 },
      heading: { family: "'Plus Jakarta Sans', sans-serif", weight: '600', style: 'normal', letterSpacing: 0.5, align: 'left', offsetY: 0 },
      contact: { family: "'Roboto', sans-serif", weight: '500', style: 'normal', letterSpacing: 0.2, align: 'left', offsetY: 0 },
      description: { family: "'Inter', sans-serif", weight: '400', style: 'normal', letterSpacing: 0, align: 'left', offsetY: 0 }
    },
    political: {
      brand: { family: "'Oswald', sans-serif", weight: '700', style: 'normal', letterSpacing: 1.2, align: 'center', offsetY: 0 },
      heading: { family: "'Montserrat', sans-serif", weight: '800', style: 'normal', letterSpacing: 0.8, align: 'center', offsetY: 0 },
      contact: { family: "'Plus Jakarta Sans', sans-serif", weight: '600', style: 'normal', letterSpacing: 0.3, align: 'center', offsetY: 0 },
      description: { family: "'Open Sans', sans-serif", weight: '600', style: 'normal', letterSpacing: 0.2, align: 'center', offsetY: 0 }
    },
    festival: {
      brand: { family: "'Cinzel', serif", weight: '700', style: 'normal', letterSpacing: 1.8, align: 'center', offsetY: 0 },
      heading: { family: "'Great Vibes', cursive", weight: '400', style: 'normal', letterSpacing: 1.0, align: 'center', offsetY: 0 },
      contact: { family: "'Plus Jakarta Sans', sans-serif", weight: '500', style: 'normal', letterSpacing: 0.5, align: 'center', offsetY: 0 },
      description: { family: "'Cormorant Garamond', serif", weight: '600', style: 'italic', letterSpacing: 0.5, align: 'center', offsetY: 0 }
    },
    branding: {
      brand: { family: "'Plus Jakarta Sans', sans-serif", weight: '800', style: 'normal', letterSpacing: 1.0, align: 'left', offsetY: 0 },
      heading: { family: "'Montserrat', sans-serif", weight: '600', style: 'normal', letterSpacing: 0.5, align: 'left', offsetY: 0 },
      contact: { family: "'Inter', sans-serif", weight: '500', style: 'normal', letterSpacing: 0.2, align: 'left', offsetY: 0 },
      description: { family: "'Roboto', sans-serif", weight: '400', style: 'normal', letterSpacing: 0, align: 'left', offsetY: 0 }
    },
    gradient: {
      brand: { family: "'Montserrat', sans-serif", weight: '800', style: 'normal', letterSpacing: 1.2, align: 'center', offsetY: 0 },
      heading: { family: "'Plus Jakarta Sans', sans-serif", weight: '600', style: 'normal', letterSpacing: 0.5, align: 'center', offsetY: 0 },
      contact: { family: "'Inter', sans-serif", weight: '500', style: 'normal', letterSpacing: 0.4, align: 'center', offsetY: 0 },
      description: { family: "'Inter', sans-serif", weight: '400', style: 'normal', letterSpacing: 0.2, align: 'center', offsetY: 0 }
    },
    curved: {
      brand: { family: "'Playfair Display', serif", weight: '700', style: 'normal', letterSpacing: 1.2, align: 'center', offsetY: 0 },
      heading: { family: "'Plus Jakarta Sans', sans-serif", weight: '600', style: 'normal', letterSpacing: 0.6, align: 'center', offsetY: 0 },
      contact: { family: "'Plus Jakarta Sans', sans-serif", weight: '500', style: 'normal', letterSpacing: 0.3, align: 'center', offsetY: 0 },
      description: { family: "'Cormorant Garamond', serif", weight: '600', style: 'italic', letterSpacing: 0.4, align: 'center', offsetY: 0 }
    },
    wave: {
      brand: { family: "'Plus Jakarta Sans', sans-serif", weight: '800', style: 'normal', letterSpacing: 1.0, align: 'left', offsetY: 0 },
      heading: { family: "'Montserrat', sans-serif", weight: '600', style: 'normal', letterSpacing: 0.5, align: 'left', offsetY: 0 },
      contact: { family: "'Plus Jakarta Sans', sans-serif", weight: '600', style: 'normal', letterSpacing: 0.3, align: 'right', offsetY: 0 },
      description: { family: "'Inter', sans-serif", weight: '400', style: 'normal', letterSpacing: 0.2, align: 'left', offsetY: 0 }
    },
    double: {
      brand: { family: "'Cinzel', serif", weight: '700', style: 'normal', letterSpacing: 1.5, align: 'center', offsetY: 0 },
      heading: { family: "'Plus Jakarta Sans', sans-serif", weight: '600', style: 'normal', letterSpacing: 0.5, align: 'center', offsetY: 0 },
      contact: { family: "'Roboto', sans-serif", weight: '500', style: 'normal', letterSpacing: 0.3, align: 'center', offsetY: 0 },
      description: { family: "'Inter', sans-serif", weight: '400', style: 'normal', letterSpacing: 0.2, align: 'center', offsetY: 0 }
    },
    ribbon: {
      brand: { family: "'Bebas Neue', cursive", weight: '400', style: 'normal', letterSpacing: 2.0, align: 'center', offsetY: 0 },
      heading: { family: "'Montserrat', sans-serif", weight: '700', style: 'normal', letterSpacing: 0.8, align: 'center', offsetY: 0 },
      contact: { family: "'Plus Jakarta Sans', sans-serif", weight: '600', style: 'normal', letterSpacing: 0.4, align: 'center', offsetY: 0 },
      description: { family: "'Open Sans', sans-serif", weight: '600', style: 'normal', letterSpacing: 0.2, align: 'center', offsetY: 0 }
    },
    transparent: {
      brand: { family: "'Inter', sans-serif", weight: '700', style: 'normal', letterSpacing: 1.2, align: 'center', offsetY: 0 },
      heading: { family: "'Plus Jakarta Sans', sans-serif", weight: '500', style: 'normal', letterSpacing: 0.6, align: 'center', offsetY: 0 },
      contact: { family: "'Inter', sans-serif", weight: '400', style: 'normal', letterSpacing: 0.3, align: 'center', offsetY: 0 },
      description: { family: "'Inter', sans-serif", weight: '400', style: 'normal', letterSpacing: 0.2, align: 'center', offsetY: 0 }
    },
    premium_3d: {
      brand: { family: "'Cinzel', serif", weight: '800', style: 'normal', letterSpacing: 2.0, align: 'center', offsetY: 0 },
      heading: { family: "'Playfair Display', serif", weight: '700', style: 'normal', letterSpacing: 0.8, align: 'center', offsetY: 0 },
      contact: { family: "'Plus Jakarta Sans', sans-serif", weight: '600', style: 'normal', letterSpacing: 0.5, align: 'center', offsetY: 0 },
      description: { family: "'Cormorant Garamond', serif", weight: '600', style: 'italic', letterSpacing: 0.4, align: 'center', offsetY: 0 }
    },
    split: {
      brand: { family: "'Montserrat', sans-serif", weight: '800', style: 'normal', letterSpacing: 1.2, align: 'left', offsetY: 0 },
      heading: { family: "'Plus Jakarta Sans', sans-serif", weight: '600', style: 'normal', letterSpacing: 0.5, align: 'left', offsetY: 0 },
      contact: { family: "'Roboto', sans-serif", weight: '500', style: 'normal', letterSpacing: 0.2, align: 'left', offsetY: 0 },
      description: { family: "'Inter', sans-serif", weight: '400', style: 'normal', letterSpacing: 0, align: 'left', offsetY: 0 }
    },
    image_based: {
      brand: { family: "'Playfair Display', serif", weight: '700', style: 'normal', letterSpacing: 1.4, align: 'center', offsetY: 0 },
      heading: { family: "'Montserrat', sans-serif", weight: '600', style: 'normal', letterSpacing: 0.6, align: 'center', offsetY: 0 },
      contact: { family: "'Plus Jakarta Sans', sans-serif", weight: '500', style: 'normal', letterSpacing: 0.4, align: 'center', offsetY: 0 },
      description: { family: "'Inter', sans-serif", weight: '400', style: 'normal', letterSpacing: 0.2, align: 'center', offsetY: 0 }
    },
    logo_focused: {
      brand: { family: "'Montserrat', sans-serif", weight: '800', style: 'normal', letterSpacing: 1.2, align: 'center', offsetY: 0 },
      heading: { family: "'Plus Jakarta Sans', sans-serif", weight: '600', style: 'normal', letterSpacing: 0.5, align: 'center', offsetY: 0 },
      contact: { family: "'Roboto', sans-serif", weight: '500', style: 'normal', letterSpacing: 0.3, align: 'center', offsetY: 0 },
      description: { family: "'Inter', sans-serif", weight: '400', style: 'normal', letterSpacing: 0.2, align: 'center', offsetY: 0 }
    },
    photo_focused: {
      brand: { family: "'Montserrat', sans-serif", weight: '700', style: 'normal', letterSpacing: 1.0, align: 'left', offsetY: 0 },
      heading: { family: "'Oswald', sans-serif", weight: '700', style: 'normal', letterSpacing: 0.8, align: 'left', offsetY: 0 },
      contact: { family: "'Plus Jakarta Sans', sans-serif", weight: '600', style: 'normal', letterSpacing: 0.3, align: 'left', offsetY: 0 },
      description: { family: "'Plus Jakarta Sans', sans-serif", weight: '500', style: 'normal', letterSpacing: 0.2, align: 'left', offsetY: 0 }
    }
  };

  // Active state storage
  let currentConfig = JSON.parse(JSON.stringify(STYLE_PAIRINGS.wave));
  let autoSelectionEnabled = true;

  /**
   * Get font configuration for a specific role ('brand', 'heading', 'contact', 'description')
   */
  function getRoleConfig(role) {
    return currentConfig[role] || currentConfig.brand;
  }

  /**
   * Set custom typography configuration for a role
   */
  function setRoleConfig(role, changes) {
    if (!currentConfig[role]) {
      currentConfig[role] = { family: "'Plus Jakarta Sans', sans-serif", weight: '600', style: 'normal', letterSpacing: 0.5, align: 'left', offsetY: 0 };
    }
    Object.assign(currentConfig[role], changes);
  }

  /**
   * Automatically select best typography pairing for a chosen footer shape or theme
   */
  function autoSelectForTheme(shapeOrTheme) {
    const key = (shapeOrTheme || 'wave').toLowerCase();
    const preset = STYLE_PAIRINGS[key] || STYLE_PAIRINGS.wave;
    currentConfig = JSON.parse(JSON.stringify(preset));
    return currentConfig;
  }

  /**
   * Format CSS/Canvas font string
   */
  function formatFontString(fontSize, role) {
    const cfg = getRoleConfig(role);
    const stylePart = cfg.style === 'italic' ? 'italic ' : '';
    const weightPart = cfg.weight || '600';
    const familyPart = cfg.family || "'Plus Jakarta Sans', sans-serif";
    return `${stylePart}${weightPart} ${Math.round(fontSize)}px ${familyPart}`;
  }

  /**
   * Calculate adaptive font size with bounds checking to avoid clipping or overflow
   */
  function calculateAdaptiveFontSize(text, role, maxW, baseSize, minLimit = 10.5, ctx = null) {
    if (!text) return baseSize;
    let size = baseSize;

    // If text is short, can give a tiny visual boost (max +15%)
    if (text.length < 12 && role === 'brand') {
      size = Math.min(baseSize * 1.15, 26);
    }

    if (!ctx) return size;

    ctx.save();
    ctx.font = formatFontString(size, role);
    const cfg = getRoleConfig(role);
    if (ctx.letterSpacing !== undefined && cfg.letterSpacing) {
      ctx.letterSpacing = `${cfg.letterSpacing}px`;
    }

    let measuredW = ctx.measureText(text).width;
    while (measuredW > maxW && size > minLimit) {
      size -= 0.5;
      ctx.font = formatFontString(size, role);
      measuredW = ctx.measureText(text).width;
    }
    ctx.restore();

    return Math.max(minLimit, size);
  }

  /**
   * Draw text on Canvas with full typography controls (letterSpacing, alignment, offsetY)
   */
  function drawText(ctx, text, x, y, options = {}) {
    if (!text || !ctx) return;
    const role = options.role || 'brand';
    const cfg = getRoleConfig(role);
    const fontSize = options.fontSize || 14;
    const color = options.color || '#ffffff';
    const align = options.align || cfg.align || 'left';
    const letterSpacing = (options.letterSpacing !== undefined) ? options.letterSpacing : cfg.letterSpacing;
    const offsetY = (options.offsetY !== undefined) ? options.offsetY : (cfg.offsetY || 0);

    ctx.save();
    ctx.font = formatFontString(fontSize, role);
    ctx.fillStyle = color;
    ctx.textAlign = align;
    ctx.textBaseline = options.textBaseline || 'middle';

    if (letterSpacing && ctx.letterSpacing !== undefined) {
      ctx.letterSpacing = `${letterSpacing}px`;
    }

    ctx.fillText(text, x, y + offsetY);
    ctx.restore();
  }

  return {
    FONT_CATALOG,
    ALL_FONTS,
    STYLE_PAIRINGS,
    getRoleConfig,
    setRoleConfig,
    autoSelectForTheme,
    formatFontString,
    calculateAdaptiveFontSize,
    drawText,
    isAutoSelectionEnabled: () => autoSelectionEnabled,
    setAutoSelectionEnabled: (val) => { autoSelectionEnabled = !!val; },
    getAllConfig: () => currentConfig,
    setAllConfig: (cfg) => { currentConfig = JSON.parse(JSON.stringify(cfg)); }
  };
}));
