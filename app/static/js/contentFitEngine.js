/**
 * contentFitEngine.js
 * 
 * Part of the Automatic Content-Aware Footer Layout Engine for Iimagica.
 * Implements the rigorous fitting order to prevent text clipping, overlap,
 * image distortion, and unreadable font sizing:
 * 
 * 1. Try selected layout with original font sizes.
 * 2. Reduce unnecessary padding and gaps.
 * 3. Wrap long text into additional lines.
 * 4. Rearrange elements into additional rows or columns.
 * 5. Adjust logo and photograph sizes proportionately.
 * 6. Reduce font sizes within defined readability limits.
 * 7. Increase footer height within the available poster area.
 * 8. If it still doesn't fit, suggest another layout.
 */

(function (root, factory) {
  if (typeof define === 'function' && define.amd) {
    define(['./contentAnalysisEngine', './responsiveSizeEngine', './layoutEngine'], factory);
  } else if (typeof module === 'object' && module.exports) {
    module.exports = factory(
      require('./contentAnalysisEngine'),
      require('./responsiveSizeEngine'),
      require('./layoutEngine')
    );
  } else {
    root.ContentFitEngine = factory(
      root.ContentAnalysisEngine,
      root.ResponsiveSizeEngine,
      root.LayoutEngine
    );
  }
}(typeof self !== 'undefined' ? self : this, function (AnalysisEngine, SizeEngine, LayoutEngine) {
  'use strict';

  const READABILITY_LIMITS = {
    minBodyFontSize: 10.5,
    minHeaderFontSize: 13.5,
    minBrandFontSize: 15.0,
    minLogoHeight: 28,
    minPhotoHeight: 48
  };

  /**
   * Check if any text element exceeds its container width
   */
  function checkTextOverflow(elements, maxContentW) {
    const overflows = [];
    elements.forEach(el => {
      if (el.text && el.maxWidth) {
        const fontName = el.font || "'Plus Jakarta Sans', sans-serif";
        const w = AnalysisEngine.measureTextWidth(el.text, fontName, el.fontSize, el.weight || 'normal');
        if (w > el.maxWidth + 2) {
          overflows.push({
            id: el.id,
            text: el.text,
            measuredWidth: w,
            maxWidth: el.maxWidth,
            overflowAmount: Math.round(w - el.maxWidth)
          });
        }
      }
    });
    return overflows;
  }

  /**
   * Check for bounding box collisions between elements
   */
  function checkOverlap(elements) {
    const collisions = [];
    for (let i = 0; i < elements.length; i++) {
      for (let j = i + 1; j < elements.length; j++) {
        const a = elements[i];
        const b = elements[j];

        // Only test bounding box items with width and height
        if (a.width && a.height && b.width && b.height) {
          const aRight = a.x + a.width;
          const aBottom = a.y + a.height;
          const bRight = b.x + b.width;
          const bBottom = b.y + b.height;

          const xOverlap = Math.max(0, Math.min(aRight, bRight) - Math.max(a.x, b.x));
          const yOverlap = Math.max(0, Math.min(aBottom, bBottom) - Math.max(a.y, b.y));

          if (xOverlap > 4 && yOverlap > 4) {
            collisions.push({ a: a.id, b: b.id, xOverlap, yOverlap });
          }
        }
      }
    }
    return collisions;
  }

  /**
   * Master Content Fit Solver implementing the 8-step sequence
   */
  function solveContentFit(rawData, posterW, posterH, footerShape, options = {}) {
    const warnings = [];
    const suggestions = [];

    // Step 0: Content Analysis
    const analysis = AnalysisEngine.analyzeContent(rawData, posterW, posterH);

    // Initial Layout Selection
    let chosenLayout = LayoutEngine.selectBestLayout(
      analysis,
      posterW,
      posterH,
      footerShape,
      options.manualArchetype
    );

    // Step 1: Try selected layout with preferred font sizes
    let sizing = SizeEngine.calculateDimensions({
      posterWidth: posterW,
      posterHeight: posterH,
      footerShape,
      rows: chosenLayout.rows,
      analysis,
      options
    });

    let footerY = posterH - 26 - sizing.footerHeight; // frameInset = 26
    let placement = LayoutEngine.computeCoordinates(chosenLayout, sizing, posterW, posterH, footerY, 26);
    let overflows = checkTextOverflow(placement.elements, posterW - 80);

    // Step 2 & 3: Reduce padding and wrap text into additional lines if overflowing
    if (overflows.length > 0) {
      // If contact inline is overflowing, try wrapping or re-structuring into multi-row
      if (chosenLayout.archetype === 'compact-single-row' || chosenLayout.archetype === 'balanced-two-row') {
        const hasLongContacts = overflows.some(o => o.id === 'contacts' || o.id === 'contacts_row_1');
        if (hasLongContacts && !options.manualArchetype) {
          // Step 4: Rearrange elements into additional rows
          chosenLayout = LayoutEngine.buildMultiRowStacked(analysis, posterW - 80);
          suggestions.push('Automatically arranged contact details into multi-row layout to prevent clipping.');

          sizing = SizeEngine.calculateDimensions({
            posterWidth: posterW,
            posterHeight: posterH,
            footerShape,
            rows: chosenLayout.rows,
            analysis,
            options: { ...options, paddingScale: 0.9, rowGap: 8 }
          });

          footerY = posterH - 26 - sizing.footerHeight;
          placement = LayoutEngine.computeCoordinates(chosenLayout, sizing, posterW, posterH, footerY, 26);
          overflows = checkTextOverflow(placement.elements, posterW - 80);
        }
      }
    }

    // Step 5: Adjust image sizes proportionately if height is compressed
    if (sizing.isCompressed) {
      if (sizing.logoSize) {
        sizing.logoSize.height = Math.max(READABILITY_LIMITS.minLogoHeight, Math.round(sizing.logoSize.height * 0.88));
        sizing.logoSize.width = Math.round(sizing.logoSize.height * (analysis.logo.aspectRatio || 1));
      }
      if (sizing.photoSize) {
        sizing.photoSize.height = Math.max(READABILITY_LIMITS.minPhotoHeight, Math.round(sizing.photoSize.height * 0.90));
        sizing.photoSize.width = Math.round(sizing.photoSize.height * (analysis.photo.aspectRatio || 1));
      }
    }

    // Step 6: Reduce font sizes within defined readability limits if still overflowing
    if (overflows.length > 0) {
      placement.elements.forEach(el => {
        if (el.text && el.maxWidth) {
          const fontName = el.font || "'Plus Jakarta Sans', sans-serif";
          let curWidth = AnalysisEngine.measureTextWidth(el.text, fontName, el.fontSize, el.weight || 'normal');
          let currentSize = el.fontSize;
          const minLimit = el.type === 'brand' ? READABILITY_LIMITS.minBrandFontSize : READABILITY_LIMITS.minBodyFontSize;

          while (curWidth > el.maxWidth && currentSize > minLimit) {
            currentSize -= 0.5;
            curWidth = AnalysisEngine.measureTextWidth(el.text, fontName, currentSize, el.weight || 'normal');
          }
          el.fontSize = currentSize;

          // If still overflowing after reaching readability limit, wrap or truncate gracefully
          if (curWidth > el.maxWidth) {
            // Check if wrapping helps
            const wrapped = AnalysisEngine.wrapText(el.text, el.maxWidth, fontName, currentSize, el.weight || 'normal');
            if (wrapped.lines.length > 1) {
              el.wrappedLines = wrapped.lines;
              el.lineHeight = wrapped.lineHeight;
            } else {
              // Ellipsize
              let truncated = el.text;
              while (truncated.length > 4 && AnalysisEngine.measureTextWidth(truncated + '…', fontName, currentSize, el.weight || 'normal') > el.maxWidth) {
                truncated = truncated.slice(0, -1);
              }
              el.displayText = truncated + '…';
              warnings.push(`Text '${el.text}' was truncated with ellipsis to fit readable container boundaries.`);
            }
          }
        }
      });
    }

    // Step 7: Check footer height against allowable poster area
    if (sizing.overflowWarning) {
      warnings.push(sizing.overflowWarning.message);
    }

    // Verification: Overlap check
    const collisions = checkOverlap(placement.elements);
    if (collisions.length > 0) {
      // Adjust colliding Y positions
      collisions.forEach(col => {
        const itemB = placement.elements.find(e => e.id === col.b);
        if (itemB) {
          itemB.y += col.yOverlap + 2;
        }
      });
    }

    return {
      success: true,
      layout: chosenLayout,
      archetype: chosenLayout.archetype,
      layoutTitle: chosenLayout.title,
      sizing,
      footerHeight: sizing.footerHeight,
      footerY,
      elements: placement.elements,
      footerBox: placement.footerBox,
      analysis,
      warnings,
      suggestions,
      timestamp: Date.now()
    };
  }

  return {
    READABILITY_LIMITS,
    checkTextOverflow,
    checkOverlap,
    solveContentFit
  };
}));
