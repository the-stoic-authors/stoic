/* Stoic ELN — Stoichiometry auto-calculator (client-side).
 *
 * In the reaction component table, when the user types into one stoichiometry
 * cell (eq, mmol, g, mL), the others are recalculated. The "limiting reagent"
 * row (data-limiting="true") drives the eq → mmol conversion.
 *
 * Each row has data attributes:
 *   data-row-index    integer  - row position in the table
 *   data-mw           float    - MW (g/mol)   (may be 0/empty if unknown)
 *   data-density      float    - ρ (g/mL)     (may be 0/empty if unknown)
 *   data-limiting     "true"|"false"
 *
 * Each input cell has class "stoich-input" and one of:
 *   data-field="eq" | "mmol" | "g" | "mL"
 *
 * The result is propagated server-side at form submit; this script only fills
 * in the cells visually so the chemist can sanity-check before saving.
 */

(function () {
  function val(el) {
    if (!el) return null;
    const v = el.value.trim();
    if (v === "" || v === "—") return null;
    const f = parseFloat(v.replace(",", "."));
    return isFinite(f) && f > 0 ? f : null;
  }

  function setVal(el, value, opts) {
    if (!el) return;
    if (value === null || !isFinite(value)) {
      el.value = "";
      return;
    }
    const formatted = (opts && opts.precision) || 4;
    el.value = parseFloat(value.toPrecision(formatted));
  }

  function getRowInputs(row) {
    return {
      eq: row.querySelector('[data-field="eq"]'),
      mmol: row.querySelector('[data-field="mmol"]'),
      g: row.querySelector('[data-field="g"]'),
      mL: row.querySelector('[data-field="mL"]'),
    };
  }

  function getLimitingMmol() {
    const rows = document.querySelectorAll('.stoich-row[data-limiting="true"]');
    for (const row of rows) {
      const inputs = getRowInputs(row);
      const mmol = val(inputs.mmol);
      if (mmol !== null) return mmol;
    }
    return null;
  }

  function recomputeRow(row, sourceField) {
    const inputs = getRowInputs(row);
    const mw = parseFloat(row.dataset.mw) || null;
    const density = parseFloat(row.dataset.density) || null;
    const isLimiting = row.dataset.limiting === "true";
    const limitingMmol = isLimiting ? val(inputs.mmol) : getLimitingMmol();

    const eq = val(inputs.eq);
    const mmol = val(inputs.mmol);
    const g = val(inputs.g);
    const mL = val(inputs.mL);

    let newMmol = null;
    let newG = null;
    let newML = null;
    let newEq = null;

    // Source-of-truth: whichever field the user just edited
    switch (sourceField) {
      case "g":
        if (g === null) break;
        newG = g;
        if (mw && mw > 0) newMmol = (g * 1000) / mw;
        if (density && density > 0) newML = g / density;
        if (newMmol !== null && limitingMmol && !isLimiting) newEq = newMmol / limitingMmol;
        break;

      case "mL":
        if (mL === null || !density || density <= 0) break;
        newML = mL;
        newG = mL * density;
        if (mw && mw > 0) newMmol = (newG * 1000) / mw;
        if (newMmol !== null && limitingMmol && !isLimiting) newEq = newMmol / limitingMmol;
        break;

      case "mmol":
        if (mmol === null) break;
        newMmol = mmol;
        if (mw && mw > 0) {
          newG = (mmol * mw) / 1000;
          if (density && density > 0) newML = newG / density;
        }
        if (limitingMmol && !isLimiting) newEq = mmol / limitingMmol;
        break;

      case "eq":
        if (eq === null || !limitingMmol || isLimiting) break;
        newEq = eq;
        newMmol = eq * limitingMmol;
        if (mw && mw > 0) {
          newG = (newMmol * mw) / 1000;
          if (density && density > 0) newML = newG / density;
        }
        break;
    }

    // Update the row UI (skip the source field — user is typing there)
    if (sourceField !== "eq") setVal(inputs.eq, newEq);
    if (sourceField !== "mmol") setVal(inputs.mmol, newMmol);
    if (sourceField !== "g") setVal(inputs.g, newG);
    if (sourceField !== "mL") setVal(inputs.mL, newML);
  }

  function recomputeAllNonLimiting() {
    // When the limiting reagent's mmol changes, every other row's eq→mmol
    // conversion needs to be redone.
    const limiting = getLimitingMmol();
    if (limiting === null) return;
    document.querySelectorAll('.stoich-row[data-limiting="false"]').forEach((row) => {
      const inputs = getRowInputs(row);
      const eq = val(inputs.eq);
      if (eq !== null) {
        // Treat eq as authoritative for non-limiting rows
        recomputeRow(row, "eq");
      }
    });
  }

  function bind() {
    const inputs = document.querySelectorAll(".stoich-input");
    inputs.forEach((input) => {
      input.addEventListener("input", (e) => {
        const row = e.target.closest(".stoich-row");
        const field = e.target.dataset.field;
        if (!row || !field) return;
        recomputeRow(row, field);
        // If the limiting row's mmol changed, ripple through to all non-limiting
        if (row.dataset.limiting === "true" && field !== "eq") {
          recomputeAllNonLimiting();
        }
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
  document.body.addEventListener("htmx:afterSwap", bind);
})();
