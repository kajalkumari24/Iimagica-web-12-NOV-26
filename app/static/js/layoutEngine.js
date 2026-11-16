/**
 * layoutEngine.js
 * 
 * Part of the Automatic Content-Aware Footer Layout Engine for Iimagica.
 * Generates candidate layouts (single-row, balanced two-row, multi-row,
 * 3-column grid, photo-focused), evaluates them for readability, visual balance,
 * and space utilization, and computes exact pixel coordinates for each element.
 */

(function (root, factory) {
  if (typeof define === 'function' && define.amd) {
    define(['./contentAnalysisEngine', './responsiveSizeEngine'], factory);
  } else if (typeof module === 'object' && module.exports) {
    module.exports = factory(require('./contentAnalysisEngine'), require('./responsiveSizeEngine'));
  } else {
    root.LayoutEngine = factory(root.ContentAnalysisEngine, root.ResponsiveSizeEngine);
  }
}(typeof self !== 'undefined' ? self : this, function (AnalysisEngine, SizeEngine) {
  'use strict';

  /**
   * Layout Archetype Builders
   */

  // 1. Compact Single Row Layout (Best for minimal info: Logo + Name + 1-2 contacts)
  function buildCompactSingleRow(analysis, availableW) {
    const row = [];

    if (analysis.hasLogo) {
      row.push({
        type: 'logo',
        id: 'logo',
        width: 44,
        height: 44,
        align: 'left'
      });
    }

    if (analysis.hasBrand) {
      row.push({
        type: 'brand',
        id: 'brand',
        text: analysis.brand.text,
        fontSize: 16,
        weight: '800',
        align: 'left'
      });
    }

    // Contacts
    const contactTexts = analysis.contacts.slice(0, 3).map(c => c.displayText);
    if (contactTexts.length > 0) {
      row.push({
        type: 'contacts_inline',
        id: 'contacts',
        items: analysis.contacts.slice(0, 3),
        text: contactTexts.join('   •   '),
        fontSize: 12.5,
        weight: '600',
        align: 'right'
      });
    }

    return {
      archetype: 'compact-single-row',
      title: 'Compact Single-Row',
      rows: [row],
      columnMode: false
    };
  }

  // 2. Balanced Two-Row Layout (The standard workhorse for balanced branding)
  function buildBalancedTwoRow(analysis, availableW) {
    const row1 = [];
    const row2 = [];

    // Row 1: Brand identity, Logo & Tagline
    if (analysis.hasLogo) {
      row1.push({
        type: 'logo',
        id: 'logo',
        width: 48,
        height: 48,
        align: 'left'
      });
    }

    if (analysis.hasBrand) {
      row1.push({
        type: 'brand',
        id: 'brand',
        text: analysis.brand.text,
        fontSize: 20,
        weight: '800',
        align: analysis.hasLogo ? 'left' : 'center'
      });
    }

    if (analysis.hasPerson) {
      row1.push({
        type: 'person',
        id: 'person',
        name: analysis.person.name,
        role: analysis.person.role,
        text: analysis.person.role ? `${analysis.person.name} (${analysis.person.role})` : analysis.person.name,
        fontSize: 14.5,
        weight: '700',
        align: 'center'
      });
    }

    if (analysis.hasTagline && !analysis.hasPerson) {
      row1.push({
        type: 'tagline',
        id: 'tagline',
        text: analysis.tagline.text,
        fontSize: 14.5,
        weight: '600',
        align: 'center'
      });
    }

    // Row 2: Contacts
    if (analysis.hasContacts) {
      const contactTexts = analysis.contacts.map(c => c.displayText);
      row2.push({
        type: 'contacts_inline',
        id: 'contacts',
        items: analysis.contacts,
        text: contactTexts.join('   •   '),
        fontSize: 13,
        weight: '600',
        align: 'center'
      });
    } else if (analysis.hasTagline && analysis.hasPerson) {
      row2.push({
        type: 'tagline',
        id: 'tagline',
        text: analysis.tagline.text,
        fontSize: 13.5,
        weight: '600',
        align: 'center'
      });
    }

    return {
      archetype: 'balanced-two-row',
      title: 'Balanced Two-Row',
      rows: [row1, row2].filter(r => r.length > 0),
      columnMode: false
    };
  }

  // 3. Multi-Row Stacked Layout (Best for rich content: Addresses, WhatsApp, Instagram)
  function buildMultiRowStacked(analysis, availableW) {
    const rows = [];

    // Row 1: Header / Brand & Logo
    const headerRow = [];
    if (analysis.hasLogo) {
      headerRow.push({ type: 'logo', id: 'logo', width: 44, height: 44, align: 'left' });
    }
    if (analysis.hasBrand) {
      headerRow.push({ type: 'brand', id: 'brand', text: analysis.brand.text, fontSize: 19, weight: '800', align: 'left' });
    }
    if (analysis.hasTagline) {
      headerRow.push({ type: 'tagline', id: 'tagline', text: analysis.tagline.text, fontSize: 13.5, weight: '600', align: 'right' });
    }
    if (headerRow.length > 0) rows.push(headerRow);

    // Row 2: Person Name & Designation (if present)
    if (analysis.hasPerson) {
      rows.push([{
        type: 'person',
        id: 'person',
        name: analysis.person.name,
        role: analysis.person.role,
        text: analysis.person.role ? `${analysis.person.name}  —  ${analysis.person.role}` : analysis.person.name,
        fontSize: 14.5,
        weight: '700',
        align: 'center'
      }]);
    }

    // Contact Rows (Split into 2 balanced rows if count >= 3)
    const contacts = analysis.contacts;
    if (contacts.length <= 3) {
      rows.push([{
        type: 'contacts_inline',
        id: 'contacts_row_1',
        items: contacts,
        text: contacts.map(c => c.displayText).join('   •   '),
        fontSize: 12.5,
        weight: '600',
        align: 'center'
      }]);
    } else {
      const mid = Math.ceil(contacts.length / 2);
      const rowA = contacts.slice(0, mid);
      const rowB = contacts.slice(mid);

      rows.push([{
        type: 'contacts_inline',
        id: 'contacts_row_1',
        items: rowA,
        text: rowA.map(c => c.displayText).join('   •   '),
        fontSize: 12.5,
        weight: '600',
        align: 'center'
      }]);

      rows.push([{
        type: 'contacts_inline',
        id: 'contacts_row_2',
        items: rowB,
        text: rowB.map(c => c.displayText).join('   •   '),
        fontSize: 12.5,
        weight: '600',
        align: 'center'
      }]);
    }

    return {
      archetype: 'multi-row-stacked',
      title: 'Multi-Row Stacked',
      rows,
      columnMode: false
    };
  }

  // 4. Photo-Focused Layout (Dedicated portrait/badge layout when a person photo is uploaded)
  function buildPhotoFocused(analysis, availableW) {
    const photoBadge = {
      type: 'person_photo',
      id: 'person_photo',
      width: 78,
      height: 96,
      align: 'left'
    };

    // Right-side rows beside the photo badge
    const contentRows = [];

    // Side Row 1: Brand & Person Name
    const nameLine = analysis.hasPerson
      ? (analysis.person.role ? `${analysis.person.name} • ${analysis.person.role}` : analysis.person.name)
      : (analysis.brand.text || 'Celebration');

    contentRows.push([{
      type: 'person',
      id: 'person_header',
      text: nameLine,
      fontSize: 17,
      weight: '800',
      align: 'left'
    }]);

    // Side Row 2: Tagline or Brand
    if (analysis.hasTagline || (analysis.hasBrand && analysis.hasPerson)) {
      contentRows.push([{
        type: 'tagline',
        id: 'side_tagline',
        text: analysis.tagline.text || analysis.brand.text,
        fontSize: 13,
        weight: '600',
        align: 'left'
      }]);
    }

    // Side Row 3: Contacts (split or inline)
    if (analysis.hasContacts) {
      const contactTexts = analysis.contacts.slice(0, 4).map(c => c.displayText);
      contentRows.push([{
        type: 'contacts_inline',
        id: 'side_contacts',
        items: analysis.contacts.slice(0, 4),
        text: contactTexts.join('   •   '),
        fontSize: 12,
        weight: '600',
        align: 'left'
      }]);
    }

    return {
      archetype: 'photo-focused',
      title: 'Photo-Focused Badge',
      hasPhotoColumn: true,
      photoBadge,
      rows: contentRows,
      columnMode: true
    };
  }

  // 5. Three-Column Grid Layout (Logo left | Message center | Contacts right)
  function buildThreeColumnGrid(analysis, availableW) {
    const colLeft = [];
    if (analysis.hasLogo) {
      colLeft.push({ type: 'logo', id: 'logo', width: 52, height: 52, align: 'center' });
    }

    const colCenter = [];
    if (analysis.hasBrand) {
      colCenter.push({ type: 'brand', id: 'brand', text: analysis.brand.text, fontSize: 18, weight: '800', align: 'center' });
    }
    if (analysis.hasTagline) {
      colCenter.push({ type: 'tagline', id: 'tagline', text: analysis.tagline.text, fontSize: 13, weight: '600', align: 'center' });
    }

    const colRight = [];
    analysis.contacts.slice(0, 3).forEach((c, idx) => {
      colRight.push({
        type: 'contact_item',
        id: `contact_col_${idx}`,
        text: c.displayText,
        fontSize: 12,
        weight: '600',
        align: 'right'
      });
    });

    return {
      archetype: 'three-column-grid',
      title: 'Three-Column Grid',
      columns: [
        { id: 'left', elements: colLeft, widthRatio: 0.22 },
        { id: 'center', elements: colCenter, widthRatio: 0.44 },
        { id: 'right', elements: colRight, widthRatio: 0.34 }
      ],
      rows: [[...colLeft, ...colCenter, ...colRight]], // fallback row projection
      columnMode: true
    };
  }

  /**
   * Layout Evaluator & Quality Scorer
   * Evaluates suitability, readability, visual balance, and space efficiency.
   */
  function evaluateLayout(candidate, analysis, posterW, posterH, footerShape) {
    let score = 100;

    // 1. Photo presence alignment
    if (analysis.hasPhoto) {
      if (candidate.archetype === 'photo-focused') {
        score += 35; // Strongly favor photo-focused archetype when photo is uploaded
      } else {
        score -= 25; // Penalize standard layouts that don't dedicate proper badge space for photo
      }
    } else {
      if (candidate.archetype === 'photo-focused') {
        return -999; // Never pick photo-focused layout if there is no photograph
      }
    }

    // 2. Content Volume Matching
    if (analysis.contentTier === 'small') {
      if (candidate.archetype === 'compact-single-row') score += 25;
      if (candidate.archetype === 'balanced-two-row') score += 15;
      if (candidate.archetype === 'multi-row-stacked') score -= 20; // overly sparse
    } else if (analysis.contentTier === 'medium') {
      if (candidate.archetype === 'balanced-two-row') score += 25;
      if (candidate.archetype === 'three-column-grid') score += 18;
      if (candidate.archetype === 'compact-single-row') score -= 30; // cramped
    } else if (analysis.contentTier === 'large') {
      if (candidate.archetype === 'multi-row-stacked') score += 30;
      if (candidate.archetype === 'compact-single-row') score -= 50; // text will overflow
      if (candidate.archetype === 'balanced-two-row') score += 5;
    }

    // 3. Contact Count Accommodations
    const contactCount = analysis.contacts.length;
    if (contactCount >= 4 && candidate.archetype === 'compact-single-row') {
      score -= 40;
    }

    return score;
  }

  /**
   * Generate all candidate layouts and select the winner deterministically
   */
  function selectBestLayout(analysis, posterW, posterH, footerShape, manualOverride = null) {
    const availableW = posterW - 60; // account for margins

    // Build candidates
    const candidates = [
      buildCompactSingleRow(analysis, availableW),
      buildBalancedTwoRow(analysis, availableW),
      buildMultiRowStacked(analysis, availableW),
      buildThreeColumnGrid(analysis, availableW)
    ];

    if (analysis.hasPhoto) {
      candidates.unshift(buildPhotoFocused(analysis, availableW));
    }

    // Check if manual override matches an archetype
    if (manualOverride && manualOverride !== 'auto') {
      const matched = candidates.find(c => c.archetype === manualOverride);
      if (matched) return matched;
    }

    // Score candidates
    let bestCandidate = candidates[0];
    let highestScore = -Infinity;

    candidates.forEach(cand => {
      const score = evaluateLayout(cand, analysis, posterW, posterH, footerShape);
      cand.score = score;
      if (score > highestScore) {
        highestScore = score;
        bestCandidate = cand;
      }
    });

    return bestCandidate;
  }

  /**
   * Exact Coordinate Computation Engine
   * Calculates the final X, Y, Width, and Height for every visual element.
   */
  function computeCoordinates(layout, sizing, posterW, posterH, footerY, frameInset = 26) {
    const elements = [];
    const contentW = posterW - (frameInset * 2) - 16;
    const contentX = frameInset + 8;
    const footerTopY = footerY;
    const startY = footerTopY + sizing.paddingTop;

    // Handle Photo-Focused Column Mode
    if (layout.archetype === 'photo-focused' && layout.hasPhotoColumn) {
      const photoBadge = layout.photoBadge;
      const badgeW = sizing.photoSize.width || 76;
      const badgeH = sizing.photoSize.height || 92;
      const photoX = contentX + 16;
      const photoY = startY + Math.max(0, Math.round((sizing.footerHeight - sizing.paddingTop - sizing.paddingBottom - badgeH) / 2));

      elements.push({
        type: 'person_photo',
        id: 'person_photo',
        x: photoX,
        y: photoY,
        width: badgeW,
        height: badgeH,
        borderRadius: 14
      });

      // Flow rows to the right of the photo badge
      const textStartX = photoX + badgeW + 20;
      const textAvailableW = (contentX + contentW) - textStartX - 10;
      let currentY = startY;

      layout.rows.forEach((row, rIdx) => {
        const rowH = sizing.rowHeights[rIdx] || 22;
        row.forEach(el => {
          elements.push({
            ...el,
            x: textStartX,
            y: currentY + Math.round(rowH * 0.72),
            maxWidth: textAvailableW,
            align: 'left'
          });
        });
        currentY += rowH + sizing.rowGap;
      });

      return {
        layout,
        sizing,
        elements,
        footerBox: { x: contentX, y: footerTopY, width: contentW, height: sizing.footerHeight }
      };
    }

    // Handle Three-Column Grid Mode
    if (layout.archetype === 'three-column-grid' && layout.columns) {
      const leftW = Math.round(contentW * 0.22);
      const centerW = Math.round(contentW * 0.44);
      const rightW = contentW - leftW - centerW;

      const leftX = contentX;
      const centerX = leftX + leftW;
      const rightX = centerX + centerW;
      const midY = startY + Math.round((sizing.footerHeight - sizing.paddingTop - sizing.paddingBottom) / 2);

      // Left: Logo
      layout.columns[0].elements.forEach(el => {
        const lw = sizing.logoSize.width || 48;
        const lh = sizing.logoSize.height || 48;
        elements.push({
          ...el,
          x: leftX + Math.round((leftW - lw) / 2),
          y: midY - Math.round(lh / 2),
          width: lw,
          height: lh
        });
      });

      // Center: Brand & Tagline
      let cY = startY + 6;
      layout.columns[1].elements.forEach(el => {
        elements.push({
          ...el,
          x: centerX + Math.round(centerW / 2),
          y: cY + 16,
          maxWidth: centerW - 16,
          align: 'center'
        });
        cY += 24;
      });

      // Right: Contacts Stack
      let rY = startY + 6;
      layout.columns[2].elements.forEach(el => {
        elements.push({
          ...el,
          x: rightX + rightW - 12,
          y: rY + 14,
          maxWidth: rightW - 16,
          align: 'right'
        });
        rY += 20;
      });

      return {
        layout,
        sizing,
        elements,
        footerBox: { x: contentX, y: footerTopY, width: contentW, height: sizing.footerHeight }
      };
    }

    // Standard Horizontal Rows Mode (Single-row, Balanced 2-row, Multi-row)
    let currentY = startY;

    layout.rows.forEach((row, rIdx) => {
      const rowH = sizing.rowHeights[rIdx] || 24;

      // Check if row has a logo anchored on the left
      const hasLeftLogo = row.some(el => el.type === 'logo');
      let leftOffset = 0;

      if (hasLeftLogo) {
        const logoEl = row.find(el => el.type === 'logo');
        const lw = sizing.logoSize.width || 48;
        const lh = sizing.logoSize.height || 48;
        const lx = contentX + 16;
        const ly = currentY + Math.max(0, Math.round((rowH - lh) / 2));

        elements.push({
          ...logoEl,
          x: lx,
          y: ly,
          width: lw,
          height: lh
        });
        leftOffset = lw + 18;
      }

      // Remaining elements in row
      const nonLogoEls = row.filter(el => el.type !== 'logo');

      if (nonLogoEls.length === 1) {
        const el = nonLogoEls[0];
        let elX = contentX + Math.round(contentW / 2);
        let align = el.align || 'center';

        if (hasLeftLogo) {
          elX = contentX + leftOffset + 6;
          align = 'left';
        }

        elements.push({
          ...el,
          x: elX,
          y: currentY + Math.round(rowH * 0.72),
          maxWidth: contentW - (hasLeftLogo ? leftOffset + 24 : 32),
          align
        });
      } else if (nonLogoEls.length > 1) {
        // Multi-element distributed row
        const segW = Math.round((contentW - leftOffset - 32) / nonLogoEls.length);
        nonLogoEls.forEach((el, idx) => {
          const segCenterX = contentX + leftOffset + 16 + (idx * segW) + Math.round(segW / 2);
          elements.push({
            ...el,
            x: segCenterX,
            y: currentY + Math.round(rowH * 0.72),
            maxWidth: segW - 12,
            align: el.align || 'center'
          });
        });
      }

      currentY += rowH + sizing.rowGap;
    });

    return {
      layout,
      sizing,
      elements,
      footerBox: { x: contentX, y: footerTopY, width: contentW, height: sizing.footerHeight }
    };
  }

  return {
    buildCompactSingleRow,
    buildBalancedTwoRow,
    buildMultiRowStacked,
    buildPhotoFocused,
    buildThreeColumnGrid,
    evaluateLayout,
    selectBestLayout,
    computeCoordinates
  };
}));
