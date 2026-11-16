/**
 * footerSvgRenderer.js
 * 
 * Part of the Automatic Content-Aware Footer Layout Engine for Iimagica.
 * Renders the calculated content-aware layout into a resolution-independent
 * responsive SVG with normalized viewBox and styling across 15+ professional designs.
 */

(function (root, factory) {
  if (typeof define === 'function' && define.amd) {
    define(['./typographyEngine'], factory);
  } else if (typeof module === 'object' && module.exports) {
    module.exports = factory(require('./typographyEngine'));
  } else {
    root.FooterSvgRenderer = factory(root.TypographyEngine);
  }
}(typeof self !== 'undefined' ? self : this, function (TypographyEngine) {
  'use strict';

  function escapeXml(unsafe) {
    return String(unsafe || '').replace(/[<>&'"]/g, c => {
      switch (c) {
        case '<': return '&lt;';
        case '>': return '&gt;';
        case '&': return '&amp;';
        case '\'': return '&apos;';
        case '"': return '&quot;';
      }
    });
  }

  /**
   * Generate SVG path and decorative elements for the selected footer shape
   */
  function generateShapePath(shape, W, H, topOffset = 0) {
    switch (shape) {
      case 'political':
      case 'photo_focused':
        return `M 0,${topOffset + 24} L ${W},${topOffset + 24} L ${W},${H} L 0,${H} Z`;

      case 'festival':
        return `M 0,${topOffset + 20} Q ${W * 0.25},${topOffset - 12} ${W * 0.5},${topOffset + 14} Q ${W * 0.75},${topOffset - 12} ${W},${topOffset + 20} L ${W},${H} L 0,${H} Z`;

      case 'curved':
        return `M 0,${topOffset + 22} Q ${W / 2},${topOffset - 22} ${W},${topOffset + 22} L ${W},${H} L 0,${H} Z`;

      case 'wave':
        return `M 0,${topOffset + 14} C ${W * 0.35},${topOffset - 16} ${W * 0.65},${topOffset + 16} ${W},${topOffset + 14} L ${W},${H} L 0,${H} Z`;

      case 'ribbon':
        return `M 0,${topOffset + 18} L ${W * 0.04},${topOffset + 6} L ${W * 0.96},${topOffset + 6} L ${W},${topOffset + 18} L ${W},${H} L 0,${H} Z`;

      case 'diagonal':
        return `M 0,${topOffset + 24} L ${W},${topOffset - 10} L ${W},${H} L 0,${H} Z`;

      case 'premium_3d':
      case 'corporate':
      case 'branding':
      case 'split':
      case 'gradient':
      case 'transparent':
      case 'image_based':
      case 'double':
      case 'logo_focused':
      case 'rounded':
      case 'rectangle':
      default:
        return `M 0,${topOffset} L ${W},${topOffset} L ${W},${H} L 0,${H} Z`;
    }
  }

  /**
   * Main SVG Generator
   */
  function renderSvg(solvedFit, options = {}) {
    const W = options.width || (solvedFit.footerBox ? solvedFit.footerBox.width : 1000);
    const H = solvedFit.footerHeight || 140;
    const shape = options.footerShape || 'wave';
    const themeColor = options.themeColor || '#fbbf24';
    const bgGradientStart = options.bgGradientStart || '#130d24';
    const bgGradientEnd = options.bgGradientEnd || '#241640';
    const textColor = options.textColor || '#ffffff';

    const pathData = generateShapePath(shape, W, H, 0);

    // Decorative defs and overlay shapes per template
    let extraDefs = '';
    let extraBackgroundSvg = '';

    if (shape === 'political') {
      // Saffron, White, Green tricolor accent ribbon along top
      extraBackgroundSvg = `
        <rect x="0" y="0" width="${W}" height="7" fill="#ff9933"/>
        <rect x="0" y="7" width="${W}" height="6" fill="#ffffff"/>
        <rect x="0" y="13" width="${W}" height="7" fill="#138808"/>
      `;
    } else if (shape === 'corporate') {
      // Modern corporate: dark card backdrop with crisp cyan/gold accent bar and subtle divider
      extraBackgroundSvg = `
        <line x1="0" y1="0" x2="${W}" y2="0" stroke="${themeColor}" stroke-width="4"/>
        <line x1="${W * 0.32}" y1="12" x2="${W * 0.32}" y2="${H - 12}" stroke="rgba(255,255,255,0.12)" stroke-width="1.5" stroke-dasharray="4 3"/>
      `;
    } else if (shape === 'festival') {
      // Festival: golden filigree trim with festive sparkle accents
      extraBackgroundSvg = `
        <circle cx="${W * 0.5}" cy="14" r="5" fill="${themeColor}"/>
        <circle cx="${W * 0.25}" cy="6" r="3" fill="${themeColor}" opacity="0.8"/>
        <circle cx="${W * 0.75}" cy="6" r="3" fill="${themeColor}" opacity="0.8"/>
        <line x1="0" y1="0" x2="${W}" y2="0" stroke="${themeColor}" stroke-width="2.5" stroke-dasharray="10 6"/>
      `;
    } else if (shape === 'ribbon') {
      // 3D Ribbon: stitched border effect and folded banner lines
      extraBackgroundSvg = `
        <line x1="10" y1="10" x2="${W - 10}" y2="10" stroke="${themeColor}" stroke-width="1.5" stroke-dasharray="6 4"/>
        <line x1="10" y1="${H - 10}" x2="${W - 10}" y2="${H - 10}" stroke="${themeColor}" stroke-width="1.5" stroke-dasharray="6 4"/>
      `;
    } else if (shape === 'split') {
      // Split 2-tone panel: 32% contrasting dark block, 68% tinted accent panel
      const splitX = Math.round(W * 0.33);
      extraBackgroundSvg = `
        <rect x="0" y="0" width="${splitX}" height="${H}" fill="rgba(8, 6, 16, 0.95)"/>
        <rect x="${splitX}" y="0" width="${W - splitX}" height="${H}" fill="rgba(25, 18, 48, 0.92)"/>
        <line x1="${splitX}" y1="0" x2="${splitX}" y2="${H}" stroke="${themeColor}" stroke-width="2.5"/>
      `;
    } else if (shape === 'premium_3d') {
      // 3D Beveled edge highlight on top and soft shadow
      extraBackgroundSvg = `
        <line x1="0" y1="1" x2="${W}" y2="1" stroke="rgba(255,255,255,0.4)" stroke-width="2"/>
        <line x1="0" y1="${H - 1}" x2="${W}" y2="${H - 1}" stroke="rgba(0,0,0,0.6)" stroke-width="2"/>
      `;
    } else if (shape === 'transparent') {
      // Minimal frosted glass
      extraDefs += `
        <filter id="glassBlur">
          <feGaussianBlur stdDeviation="8"/>
        </filter>
      `;
    }

    let elementsSvg = '';
    const relTop = solvedFit.footerY || 0;

    solvedFit.elements.forEach(el => {
      const localY = el.y - relTop;
      const role = (el.type === 'brand') ? 'brand' : ((el.type === 'tagline') ? 'heading' : ((el.type === 'person_title') ? 'description' : 'contact'));
      const roleCfg = (TypographyEngine && TypographyEngine.getRoleConfig) ? TypographyEngine.getRoleConfig(role) : {};

      const fontFamily = el.fontFamily || roleCfg.family || "'Plus Jakarta Sans', sans-serif";
      const fontWeight = el.weight || roleCfg.weight || '600';
      const fontStyle = el.fontStyle || roleCfg.style || 'normal';
      const letterSpacing = (el.letterSpacing !== undefined) ? el.letterSpacing : (roleCfg.letterSpacing || 0);

      if (el.type === 'logo') {
        elementsSvg += `
          <g transform="translate(${el.x}, ${localY})">
            <circle cx="${el.width / 2}" cy="${el.height / 2}" r="${el.height / 2 + 2}" fill="rgba(17,13,36,0.92)" stroke="${themeColor}" stroke-width="1.8"/>
            <image href="${escapeXml(options.logoUrl || '')}" width="${el.width}" height="${el.height}" preserveAspectRatio="xMidYMid meet"/>
          </g>`;
      } else if (el.type === 'person_photo') {
        elementsSvg += `
          <g transform="translate(${el.x}, ${localY})">
            <rect x="0" y="0" width="${el.width}" height="${el.height}" rx="12" fill="none" stroke="${themeColor}" stroke-width="2.5"/>
            <clipPath id="photoClip">
              <rect x="0" y="0" width="${el.width}" height="${el.height}" rx="12"/>
            </clipPath>
            <image href="${escapeXml(options.personPhotoUrl || '')}" width="${el.width}" height="${el.height}" preserveAspectRatio="xMidYMid slice" clip-path="url(#photoClip)"/>
          </g>`;
      } else if (el.text) {
        const anchor = el.align === 'center' ? 'middle' : (el.align === 'right' ? 'end' : 'start');
        const fill = (el.type === 'contacts_inline' || el.type === 'contact_item') ? themeColor : textColor;
        const size = el.fontSize || 13;

        elementsSvg += `
          <text x="${el.x}" y="${localY}" font-family="${fontFamily}" font-size="${size}px" font-weight="${fontWeight}" font-style="${fontStyle}" letter-spacing="${letterSpacing}px" fill="${fill}" text-anchor="${anchor}">
            ${escapeXml(el.displayText || el.text)}
          </text>`;
      }
    });

    const baseBgFill = (shape === 'transparent')
      ? 'fill="rgba(18, 14, 34, 0.45)" stroke="rgba(255,255,255,0.18)" stroke-width="1.5"'
      : (shape === 'gradient')
        ? 'fill="url(#footerMeshGrad)" stroke="rgba(255,255,255,0.25)" stroke-width="1.8"'
        : `fill="url(#footerBgGrad)" stroke="${themeColor}" stroke-width="2.5"`;

    return `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="100%" height="${H}px">
  <defs>
    <linearGradient id="footerBgGrad" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="${bgGradientStart}" stop-opacity="0.96"/>
      <stop offset="50%" stop-color="${bgGradientEnd}" stop-opacity="0.98"/>
      <stop offset="100%" stop-color="${bgGradientStart}" stop-opacity="0.96"/>
    </linearGradient>
    <linearGradient id="footerMeshGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#4f46e5" stop-opacity="0.95"/>
      <stop offset="50%" stop-color="#7c3aed" stop-opacity="0.95"/>
      <stop offset="100%" stop-color="#06b6d4" stop-opacity="0.95"/>
    </linearGradient>
    ${extraDefs}
  </defs>
  <path d="${pathData}" ${baseBgFill}/>
  ${extraBackgroundSvg}
  ${elementsSvg}
</svg>`.trim();
  }

  return {
    renderSvg,
    generateShapePath
  };
}));
