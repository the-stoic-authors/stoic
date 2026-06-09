/* Stoic ELN — Bench mode toggle
 *
 * Wires the "Bench mode" button in the run detail page to a body
 * class that, in concert with bench.css, switches the layout to a
 * tablet-friendly kiosk view. State is persisted per-run in
 * sessionStorage so reloading the page keeps the mode active.
 *
 * Activation contract:
 *   <button data-bench-toggle
 *           data-run-id="123"
 *           data-run-code="RX-001">…</button>
 *
 * When activated, a minimal topbar is injected with the run code and
 * an "Exit" button. The exit label is localised — Flask exposes it
 * via window.STOIC_BENCH_EXIT_LABEL (set in base.html).
 */
(function () {
  "use strict";

  function key(runId) {
    return "stoic.bench.run." + runId;
  }

  function injectTopbar(runCode, onExit) {
    if (document.querySelector(".bench-topbar")) return;
    var bar = document.createElement("div");
    bar.className = "bench-topbar";

    var title = document.createElement("span");
    title.className = "bench-topbar-title";
    title.textContent = runCode || "";
    bar.appendChild(title);

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "bench-topbar-exit";
    btn.innerHTML =
      '<span aria-hidden="true">✕</span>' +
      '<span class="bench-exit-label"></span>';
    btn.querySelector(".bench-exit-label").textContent =
      window.STOIC_BENCH_EXIT_LABEL || "Exit";
    btn.addEventListener("click", onExit);
    bar.appendChild(btn);

    document.body.appendChild(bar);
  }

  function removeTopbar() {
    var bar = document.querySelector(".bench-topbar");
    if (bar) bar.remove();
  }

  function activate(runId, runCode) {
    document.body.classList.add("bench-mode");
    injectTopbar(runCode, function () {
      deactivate(runId);
    });
    try {
      sessionStorage.setItem(key(runId), "1");
    } catch (e) {
      /* sessionStorage may be unavailable in some private/incognito
         modes; the in-memory class still works for the session. */
    }
    if (window.lucide && typeof window.lucide.createIcons === "function") {
      window.lucide.createIcons();
    }
  }

  function deactivate(runId) {
    document.body.classList.remove("bench-mode");
    removeTopbar();
    try {
      sessionStorage.removeItem(key(runId));
    } catch (e) {
      /* ignore */
    }
  }

  function init() {
    var btn = document.querySelector("[data-bench-toggle]");
    if (!btn) return;
    var runId = btn.getAttribute("data-run-id");
    var runCode = btn.getAttribute("data-run-code") || "";
    if (!runId) return;

    btn.addEventListener("click", function (e) {
      e.preventDefault();
      if (document.body.classList.contains("bench-mode")) {
        deactivate(runId);
      } else {
        activate(runId, runCode);
      }
    });

    // Auto-activate if the session remembers it.
    try {
      if (sessionStorage.getItem(key(runId)) === "1") {
        activate(runId, runCode);
      }
    } catch (e) {
      /* sessionStorage unavailable — never block init */
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
