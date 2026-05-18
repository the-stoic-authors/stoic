/* Stoic ELN — SmilesDrawer integration helper.
 *
 * Renders any <canvas data-smiles="..."> element using SmilesDrawer 2.2.1.
 *
 * IMPORTANT: SmilesDrawer's draw() signature requires the SECOND argument
 * to be either a string (DOM element id) or a string CSS selector. It
 * does NOT accept an HTMLCanvasElement directly — passing one triggers
 * "SyntaxError: '[object HTMLCanvasElement]' is not a valid selector"
 * because internally SmilesDrawer calls document.querySelector(arg).
 * So we ensure each canvas has an id and pass the id string.
 *
 * SmiDrawer auto-detects whether the SMILES is a single molecule or a
 * reaction (via '>' presence) and dispatches internally — no need to
 * touch ReactionDrawer ourselves.
 */

(function () {
  if (typeof SmiDrawer === "undefined") {
    console.warn("[stoic-eln] SmilesDrawer library not loaded yet");
    return;
  }

  // ACS-like classic style: short bonds, no terminal carbons, Helvetica.
  // These options match what most printed chemistry literature uses.
  const MOL_OPTIONS = {
    bondThickness: 1.0,
    bondLength: 18,           // a touch longer for better readability
    shortBondLength: 0.85,
    bondSpacing: 0.18 * 18,
    atomVisualization: "default",
    fontSizeLarge: 6,
    fontSizeSmall: 4,
    padding: 12,
    fontFamily: "Helvetica, Arial, sans-serif",
    explicitHydrogens: false,
    compactDrawing: false,    // ACS style draws full chains, not compact
    terminalCarbons: false,   // no "C" labels at chain ends (just lines)
    isomeric: true,
  };
  const REACTION_OPTIONS = {
    scale: 0.85,
    fontSize: 11,
    fontFamily: "Helvetica, Arial, sans-serif",
    spacing: 14,
    plus: { size: 14, thickness: 1.5 },
    arrow: { length: 90, headSize: 8, thickness: 1.4, margin: 8 },
  };

  let _autoIdCounter = 0;

  function currentTheme() {
    const t = document.documentElement.getAttribute("data-bs-theme");
    return t === "dark" ? "dark" : "light";
  }

  function ensureId(el) {
    if (!el.id) {
      _autoIdCounter += 1;
      el.id = "stoic-smiles-" + _autoIdCounter;
    }
    return el.id;
  }

  function drawerForCanvas(el) {
    const molOpts = Object.assign({}, MOL_OPTIONS);
    if (el.dataset.width) molOpts.width = parseInt(el.dataset.width, 10);
    if (el.dataset.height) molOpts.height = parseInt(el.dataset.height, 10);
    return new SmiDrawer(molOpts, REACTION_OPTIONS);
  }

  function resetElement(el) {
    // Clear any previous render so re-rendering after an HTMX swap
    // (e.g. when a component changes and triggers an OOB scheme update)
    // doesn't leave stale paths overlaid on top of new ones.
    while (el.firstChild) el.removeChild(el.firstChild);
    if (el.tagName.toLowerCase() === "svg") {
      // SmilesDrawer's reactionDrawer sets style.width/height in pixels
      // based on the natural content size. We clear them so a new render
      // can recompute with the (possibly different) content.
      el.style.width = "";
      el.style.height = "";
      el.removeAttribute("viewBox");
    }
  }

  function renderCanvas(el) {
    let smiles = (el.dataset.smiles || "").trim();
    if (!smiles) return;
    const id = ensureId(el);
    const theme = currentTheme();
    const drawer = drawerForCanvas(el);

    // Wipe any previous rendering — important after HTMX OOB swaps,
    // and avoids overlaying old paths when the SMILES string changed.
    resetElement(el);

    // SmilesDrawer reads `textAboveArrow` and `textBelowArrow` from
    // an inline JSON object embedded in the SMILES string itself.
    const aboveLabel = el.dataset.aboveArrowLabel;
    const belowLabel = el.dataset.belowArrowLabel;
    if (aboveLabel || belowLabel) {
      const opts = {};
      if (aboveLabel) opts.textAboveArrow = aboveLabel;
      if (belowLabel) opts.textBelowArrow = belowLabel;
      const optsStr = JSON.stringify(opts).replace(/"/g, "'");
      smiles = smiles + " __" + optsStr + "__";
    }

    drawer.draw(
      smiles,
      "#" + id,
      theme,
      null,
      function (err) {
        console.warn("[stoic-eln] SmilesDrawer error for", smiles, err);
        el.style.display = "none";
        if (el.parentElement) {
          el.parentElement.classList.add("smiles-render-failed");
        }
      },
      function (_info) { /* drawn */ },
    );
  }

  function renderAll(root) {
    const scope = root || document;
    // Match both <canvas data-smiles> (legacy) and <svg data-smiles>.
    // SVG renders are preferred for reaction schemes because the SVG
    // assumes its content's natural dimensions and scales via CSS,
    // so a reaction with many components doesn't get squished into
    // a fixed-aspect-ratio canvas buffer.
    const elems = scope.querySelectorAll("canvas[data-smiles], svg[data-smiles]");
    elems.forEach(function (el) {
      if (el.style.display === "none") return;
      try {
        renderCanvas(el);
      } catch (err) {
        console.warn("[stoic-eln] SmilesDrawer threw for", el.dataset.smiles, err);
        el.style.display = "none";
        if (el.parentElement) {
          el.parentElement.classList.add("smiles-render-failed");
        }
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { renderAll(); });
  } else {
    renderAll();
  }

  document.body.addEventListener("htmx:afterSwap", function (e) {
    // Re-render all canvases on the page, not just within the swap target.
    // OOB swaps replace elements outside e.target, so a scoped query would
    // miss the newly inserted canvas (e.g. the reaction scheme card that
    // gets swapped via hx-swap-oob when components are added/changed).
    renderAll();
  });
  document.body.addEventListener("htmx:oobAfterSwap", function (e) { renderAll(); });

  const observer = new MutationObserver(function (mutations) {
    for (const m of mutations) {
      if (m.attributeName === "data-bs-theme") {
        document.querySelectorAll("canvas[data-smiles], svg[data-smiles]")
          .forEach(function (el) {
            el.style.display = "";
            if (el.parentElement) el.parentElement.classList.remove("smiles-render-failed");
          });
        renderAll();
        return;
      }
    }
  });
  observer.observe(document.documentElement, { attributes: true });

  window.StoicSmiles = { renderAll };
})();
