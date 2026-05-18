/**
 * Stoic — GHS pictogram theme switcher.
 *
 * The official UN/UNECE GHS pictograms ship with hardcoded colours
 * inside the <svg> markup (`fill="#fff"` for the diamond background,
 * `fill="#000000"` for the symbol). Browsers load them as static
 * images, which means the page's CSS can't reach in and recolour
 * the interior — `<img>` is opaque to outer styles.
 *
 * To support Stoic's dark theme, the same SVGs are pre-generated
 * server-side with the light/dark colour palettes baked in, sitting
 * side-by-side in ``static/img/ghs/`` as ``GHSxx.svg`` (light) and
 * ``GHSxx-dark.svg`` (dark variant, white symbol on #1a1a1a, red
 * border preserved).
 *
 * This script swaps each pictogram's ``src`` to the right variant
 * based on the document's current ``data-bs-theme`` attribute, and
 * watches for runtime theme changes (theme toggle in the navbar,
 * OS-level dark/light switching for "system" theme users).
 *
 * Templates mark each pictogram with ``data-ghs-code="GHSxx"`` —
 * the script reads that to build the URL. The ``src`` attribute in
 * the template should point at the light variant; we only ever
 * rewrite it when the active theme is dark.
 */

(function () {
  "use strict";

  function ghsBasePath() {
    // The script tag is loaded with src="/static/js/ghs_theme.js" by
    // url_for('static'), so we infer the static prefix from there.
    // In practice this almost always resolves to "/static/img/ghs/",
    // but keep it derived so a deployment behind a path-prefixed
    // reverse proxy (e.g. /stoic/static/...) still works.
    const scripts = document.getElementsByTagName("script");
    for (const s of scripts) {
      const src = s.src || "";
      const idx = src.indexOf("/static/js/ghs_theme.js");
      if (idx !== -1) {
        return src.slice(0, idx) + "/static/img/ghs/";
      }
    }
    return "/static/img/ghs/";
  }

  const BASE = ghsBasePath();

  function activeTheme() {
    // <html data-bs-theme="..."> is updated both by the server (from
    // the user's chosen theme cookie) and by the early bootstrap
    // script in base.html that resolves "system" to a concrete
    // light/dark based on the OS preference.
    const t = document.documentElement.getAttribute("data-bs-theme");
    return t === "dark" ? "dark" : "light";
  }

  function srcFor(code, theme) {
    return BASE + code + (theme === "dark" ? "-dark" : "") + ".svg";
  }

  function applyTheme() {
    const theme = activeTheme();
    document.querySelectorAll("img[data-ghs-code]").forEach((img) => {
      const code = img.dataset.ghsCode;
      if (!code) return;
      const wanted = srcFor(code, theme);
      // Only write src if it actually changed — avoids unnecessary
      // image reloads that flicker on the page when toggling theme.
      if (!img.src.endsWith("/" + code + (theme === "dark" ? "-dark" : "") + ".svg")) {
        img.src = wanted;
      }
    });
  }

  // Initial pass once the DOM is ready.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", applyTheme);
  } else {
    applyTheme();
  }

  // React to theme toggles. The theme attribute can change either
  // because the user clicked the toggle (server flips
  // data-bs-theme) or because the early script in base.html resolved
  // "system" after the page parsed.
  new MutationObserver((mutations) => {
    for (const m of mutations) {
      if (m.attributeName === "data-bs-theme") {
        applyTheme();
        return;
      }
    }
  }).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-bs-theme"],
  });

  // Re-apply for HTMX-injected fragments — substance lists and the
  // detail card both use HTMX swaps that bring fresh <img> elements
  // into the DOM after the initial pass.
  document.body.addEventListener("htmx:afterSwap", applyTheme);
})();
