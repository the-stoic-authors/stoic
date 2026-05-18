/* Stoic — sticky table-header support (Settimana 6 patch 11)
 *
 * Measures the height of the sticky search bar (.stoic-sticky-search) on
 * the current page and exposes it as the CSS custom property
 * --stoic-search-h on <html>. The list templates' CSS uses this value to
 * place the sticky <thead> exactly below the search bar regardless of
 * which page is loaded or how the search bar wraps on narrower viewports.
 *
 * Listens to window resize *and* htmx:afterSwap because some search bars
 * (inventory) live inside the same partial that gets swapped — although in
 * practice the search bar itself isn't rerendered, the listener costs
 * essentially nothing and protects against future template changes.
 */
(function () {
  "use strict";

  var root = document.documentElement;

  function measure() {
    var bar = document.querySelector(".stoic-sticky-search");
    if (!bar) {
      // No search bar on this page — let CSS fall back to its default 0px.
      root.style.removeProperty("--stoic-search-h");
      return;
    }
    var h = bar.offsetHeight;
    root.style.setProperty("--stoic-search-h", h + "px");
  }

  function init() {
    measure();

    // Re-measure when the search bar's content changes (filters wrap on
    // narrow widths, the user expands an advanced-filter panel, ...).
    var bar = document.querySelector(".stoic-sticky-search");
    if (bar && window.ResizeObserver) {
      try {
        new ResizeObserver(measure).observe(bar);
      } catch (_) {
        // ResizeObserver may throw under unusual conditions — ignore and
        // fall back to the resize listener below.
      }
    }

    window.addEventListener("resize", measure, { passive: true });
    document.addEventListener("htmx:afterSwap", measure);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
