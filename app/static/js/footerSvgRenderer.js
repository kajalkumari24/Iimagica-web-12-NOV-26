/**
 * footerSvgRenderer.js
 * 
 * Part of the Automatic Content-Aware Footer Layout Engine for Iimagica.
 * Renders the calculated content-aware layout into a resolution-independent
 * responsive SVG with normalized viewBox and styling.
 */

(function (root, factory) {
  if (typeof define === 'function' && define.amd) {
    define([], factory);
  } else if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.FooterSvgRenderer = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {
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
   * Generate SVG path for the selected footer shape
   */
  function generateShapePath(shape, W, H, topOffset = 0) {
    switch (shape) {
      case 'curved':
        return `M 0,${topOffset + 20} Q ${W / 2},${topOffset - 22} ${W},${topOffset + 20} L ${W},${H} L 0,${H} Z`;
      case 'wave':
        return `M 0,${topOffset + 14} C ${W * 0.35},${topOffset - 16} ${W * 0.65},${topOffset + 16} ${W},${topOffset + 14} L ${W},${H} L 0,${H} Z`;
      case 'diagonal':
        return `M 0,${topOffset + 24} L ${W},${topOffset - 12} L ${W},${H} L 0,${H} Z`;
      case 'rounded':
        return `M 8,${topOffset + 6} Q 8,${topOffset} 16,${topOffset} L ${W - 16},${topOffset} Q ${W - 8},${topOffset} ${W - 8},${topOffset + 6} L ${W - 8},${H - 8} Q ${W - 8},${H} ${W - 16},${H} L 16,${H} Q 8,${H} 8,${H - 8} Z`;
      case 'double':
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
    const bgGradientStart = options.bgGradientStart || '#18122B';
    const bgGradientEnd = options.bgGradientEnd || '#2A1B4E';
    const textColor = options.textColor || '#ffffff';

    const pathData = generateShapePath(shape, W, H, 0);

    let elementsSvg = '';
    const relTop = solvedFit.footerY || 0;

    solvedFit.elements.forEach(el => {
      const localY = el.y - relTop;

      if (el.type === 'logo') {
        elementsSvg += `
          <g transform="translate(${el.x}, ${localY})">
            <circle cx="${el.width / 2}" cy="${el.height / 2}" r="${el.height / 2 + 2}" fill="rgba(17,13,36,0.9)" stroke="${themeColor}" stroke-width="1.8"/>
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
        const weight = el.weight || '600';
        const size = el.fontSize || 13;

        elementsSvg += `
          <text x="${el.x}" y="${localY}" font-family="'Plus Jakarta Sans', sans-serif" font-size="${size}px" font-weight="${weight}" fill="${fill}" text-anchor="${anchor}">
            ${escapeXml(el.displayText || el.text)}
          </text>`;
      }
    });

    return `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="100%" height="${H}px">
  <defs>
    <linearGradient id="footerBgGrad" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="${bgGradientStart}" stop-opacity="0.96"/>
      <stop offset="50%" stop-color="${bgGradientEnd}" stop-opacity="0.98"/>
      <stop offset="100%" stop-color="${bgGradientStart}" stop-opacity="0.96"/>
    </linearGradient>
  </defs>
  <path d="${pathData}" fill="url(#footerBgGrad)" stroke="${themeColor}" stroke-width="2.5"/>
  ${elementsSvg}
</svg>`.trim();
  }

  return {
    renderSvg,
    generateShapePath
  };
}));
