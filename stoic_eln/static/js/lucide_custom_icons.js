/* Stoic ELN — Custom Lucide icons (composite history glyphs).
 *
 * Two icons that read as "history of X" by combining the base
 * glyph (arrow-left-right for reactions, beaker for mixtures)
 * with a clock face in the lower-right.
 *
 * Addressable in templates as:
 *   <i data-lucide="reactions-history"></i>
 *   <i data-lucide="preparations-history"></i>
 *
 * Implementation: unlike most Lucide icons, these are drawn as
 * **filled** paths rather than stroked outlines. Each visible
 * line is a closed shape with two parallel sides, traced in
 * Illustrator. This means:
 *
 *   - No `stroke` attribute on the SVG root, just `fill`.
 *   - No knockout mask needed: where the clock overlaps the
 *     base glyph, the base glyph's path simply doesn't go.
 *     The "negative space" inside each filled outline is just
 *     un-painted pixels, which show whatever is behind (sidebar
 *     bg in our case, PDF white in a report, etc.).
 *
 * Inherits sidebar text colour via `fill="currentColor"`, just
 * like normal Lucide icons inherit it via stroke.
 *
 * Lookup: Lucide's createIcons() does PascalCase conversion on
 * the data-lucide attribute, so "reactions-history" looks up
 * "ReactionsHistory" in the icons object.
 *
 * Origin: SVGs designed by Rico in Adobe Illustrator and
 * provided as `arrow-left-right2.svg` / `beaker2.svg` (filled-
 * path variant, see /static/img/icons/ for the static
 * references). This file is the runtime port: Illustrator's
 * default black `fill` becomes `currentColor`, IDs and
 * Illustrator metadata are stripped.
 */

(function () {
  if (typeof lucide === "undefined") {
    console.warn("[stoic] Lucide not loaded; custom icons skipped");
    return;
  }

  // SVG root attributes — same for both icons. Note: no
  // `stroke`, no `stroke-width`: these are filled glyphs.
  const ROOT_ATTRS = {
    xmlns: "http://www.w3.org/2000/svg",
    width: 24, height: 24,
    viewBox: "0 0 24 24",
    fill: "currentColor",
  };

  // Shared clock face (a ring + a small hand-arm), already
  // designed as filled paths in Illustrator. Both icons reuse
  // exactly the same clock shapes & coordinates.
  const clockFace = [
    // Clock ring (outer + inner edge → even-odd or just two
    // overlapping subpaths; here the artist drew two paths)
    ["path", {
      d: "M16.66,22.12c-3.01,0-5.46-2.45-5.46-5.46s2.45-5.46,5.46-5.46,"
       + "5.46,2.45,5.46,5.46-2.45,5.46-5.46,5.46ZM16.66,12.2c-2.46,0-4.46,"
       + "2-4.46,4.46s2,4.46,4.46,4.46,4.46-2,4.46-4.46-2-4.46-4.46-4.46Z",
    }],
    // Clock hands (vertical + horizontal, joined at centre)
    ["path", {
      d: "M18.64,18.15c-.08,0-.15-.02-.22-.05l-1.98-.99c-.17-.08-.28-.26-.28-.45"
       + "v-2.98c0-.28.22-.5.5-.5s.5.22.5.5v2.67l1.71.85c.25.12.35.42.22.67"
       + "-.09.17-.26.28-.45.28Z",
    }],
  ];

  // ── reactions-history ──────────────────────────────────────
  const reactionsHistory = [
    "svg",
    ROOT_ATTRS,
    [
      // Top arrow: left-pointing head (as a closed filled shape)
      ["path", {
        d: "M7.2,10.2c-.2,0-.41-.08-.57-.23l-3.2-3.2c-.15-.15-.23-.35-.23-.57"
         + "s.08-.42.23-.57l3.2-3.2c.31-.31.82-.31,1.13,0,.31.31.31.82,0,1.13"
         + "l-2.63,2.63,2.63,2.63c.31.31.31.82,0,1.13-.16.16-.36.23-.57.23Z",
      }],
      // Top arrow shaft (pill-shaped horizontal bar)
      ["path", {
        d: "M16.8,7H4c-.44,0-.8-.36-.8-.8s.36-.8.8-.8h12.8c.44,0,.8.36.8.8"
         + "s-.36.8-.8.8Z",
      }],
      // Bottom arrow shaft (cropped to leave room for the clock)
      ["path", {
        d: "M11.56,13.4H4c-.44,0-.8.36-.8.8s.36.8.8.8h6.94c.11-.58.33-1.11.61-1.6Z",
      }],

      ...clockFace,
    ],
  ];

  // ── preparations-history ───────────────────────────────────
  const preparationsHistory = [
    "svg",
    ROOT_ATTRS,
    [
      // Beaker outline (single composite filled path: rim, walls,
      // base, internal liquid line, all cut where the clock sits)
      ["path", {
        d: "M10.85,17.37v-.77h-3.55c-.44,0-.8-.36-.8-.8v-3.2h5.63c.94-1.06,"
         + "2.29-1.75,3.82-1.75h.15V3.8h.4c.44,0,.8-.36.8-.8s-.36-.8-.8-.8"
         + "H4.5c-.44,0-.8.36-.8.8s.36.8.8.8h.4v12c0,1.32,1.08,2.4,2.4,2.4"
         + "h3.63c-.04-.27-.08-.55-.08-.83ZM6.5,3.8h8v7.2H6.5V3.8Z",
      }],

      ...clockFace,
    ],
  ];

  // ── Registration ───────────────────────────────────────────
  //
  // The UMD bundle exposes the icon registry in different places
  // depending on version:
  //   - newer:  lucide.icons (preferred, dedicated namespace)
  //   - older:  individual icons hung directly on the lucide global
  // We assign on both to maximise compatibility.
  if (typeof lucide.icons === "object" && lucide.icons !== null) {
    lucide.icons.ReactionsHistory = reactionsHistory;
    lucide.icons.PreparationsHistory = preparationsHistory;
  }
  try {
    lucide.ReactionsHistory = reactionsHistory;
    lucide.PreparationsHistory = preparationsHistory;
  } catch (e) {
    /* ignore — some bundles freeze the global */
  }

  // ── Manual fallback ────────────────────────────────────────
  //
  // If Lucide's createIcons() doesn't replace our custom tags
  // (older bundles, weird namespace), we walk the DOM after its
  // first pass and substitute manually.
  function iconNodeToSvgString(node) {
    if (typeof node === "string") return node;
    const [tag, attrs, children] = node;
    const attrStr = attrs
      ? " " + Object.entries(attrs)
          .map(([k, v]) => `${k}="${String(v).replace(/"/g, "&quot;")}"`)
          .join(" ")
      : "";
    const inner = (children || []).map(iconNodeToSvgString).join("");
    return inner ? `<${tag}${attrStr}>${inner}</${tag}>` : `<${tag}${attrStr}/>`;
  }

  const CUSTOM = {
    "reactions-history": reactionsHistory,
    "preparations-history": preparationsHistory,
  };

  function replaceCustomIcons(root) {
    const scope = root || document;
    for (const [name, node] of Object.entries(CUSTOM)) {
      const tags = scope.querySelectorAll(`i[data-lucide="${name}"]`);
      tags.forEach((el) => {
        const wrapper = document.createElement("div");
        wrapper.innerHTML = iconNodeToSvgString(node);
        const svg = wrapper.firstElementChild;
        if (!svg) return;
        if (el.className) svg.setAttribute("class", el.className);
        el.replaceWith(svg);
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      queueMicrotask(replaceCustomIcons);
    });
  } else {
    queueMicrotask(replaceCustomIcons);
  }
  document.body && document.body.addEventListener("htmx:afterSwap", () => {
    queueMicrotask(replaceCustomIcons);
  });
})();
