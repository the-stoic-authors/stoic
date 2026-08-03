# Patch P3 — Recorded step parameters + recrystallization & distillation procedures

Adds **recorded process parameters** to steps (distillation pressure, head
temperature, etc.) — a generic, template-declared / run-recorded structure
that mirrors the checklist architecture — plus four new seeded procedures
that use it, and renders the recorded values in the run PDF.

> Your Mac currently has **P2b only**; this delivers all of P3. Extracting
> the tarball overwrites a few files you already have (e.g. `run_step.py`,
> `run_setup.py`, `loader.py`, `procedures.py`, the EN catalog) with versions
> that keep all the P2b content and add P3 on top — safe, since P2b is
> already committed.

---

## What's in it

### 1. The parameter model (mirrors checklists across three levels)
- `models/step_template_parameter` (in `step_template.py`) — a parameter a
  library procedure declares (`label` + `unit`, no value).
- `models/step_parameter.py` (new) — the same declaration on a reaction step.
- `models/run_step.py` → `RunStepParameter` — the snapshot **plus** the
  `value` the operator records at run time (stored as text, so ranges like
  `65–68` and notes are fine).
- Relationships on `StepTemplate`, `ReactionStep`, `RunStep`
  (`.parameters`), all registered in `models/__init__.py`.

### 2. Snapshot copy paths (parallel to checklist copies)
- `procedures/routes.py` — *save to library* copies a step's parameters to
  the template; *insert into reaction* copies the template's parameters to
  the new reaction step.
- `services/run_setup.py` — launching a run copies each step's parameters to
  `RunStepParameter` (value left empty for the operator to fill).

### 3. Run-fill UI + route
- `templates/runs/detail.html` — a "Parametri registrati" block with an input
  per parameter (with its unit), HTMX-posting on change. Disabled once the run
  is completed.
- `runs/routes.py` → `set_step_parameter` — records the value (text), guarded:
  404 on bad ids / cross-run ids, blocked when the run is completed, HTMX 204.

### 4. PDF rendering
- `services/pdf_run.py` — each step now prints its recorded parameters
  (`label: value unit`) between the procedure text and the checklist.

### 5. Four new seeded procedures (`seeds/procedures.py`)
The whole procedure library is now in **English** (it was Italian) — matching
the seeded substance catalogue, and reaching the widest audience for an
open-source product. A lab can rename/edit any entry. New procedures:
- **Ricristallizzazione** (single solvent): crystallization solvent + cold
  wash + decolorizing charcoal, all ad-lib (q.b.); the ~10–20 mL/g hot-solvent
  guideline lives in the description (no computed volume, by design — the
  minimum hot volume is empirical).
- **Distillazione semplice / frazionata / sotto vuoto**: technique +
  checklist + recorded parameters. Atmospheric ones record the head-T range
  (T testa inizio/fine); the vacuum one also records Pressione (mbar) and
  T bagno. Boiling chips as a free entry where relevant.
- `seeds/loader.py` — `seed_procedures()` now also seeds a procedure's
  `parameters` (was components + checklist only).

---

## Schema

Three new, purely additive tables: `step_template_parameter`,
`step_parameter`, `run_step_parameter` (no CHECK, no changes to existing
tables). `create_all` / `ensure-schema` creates them — **no migration script
needed** (this is the sanctioned path for additive tables; the app also
self-heals its schema on boot).

---

## Apply (on your existing Mac DB, in order)

```bash
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-p3-step-parameters.tar.gz -C ~/Projects/

make ensure-schema
.venv/bin/python scripts/reseed_procedures.py
make translations
make run
```

`make ensure-schema` creates the three parameter tables.
`scripts/reseed_procedures.py` removes the four Italian P2b seed procedures
already in your library and seeds the eight English ones (the four flash/
extraction, now in English, plus recrystallization + the three distillations).
It's idempotent and safe for protocols (procedures are COPIED into reactions,
so deleting a library entry never touches a protocol that used it).
Expected: `Removed 4 existing seed procedure(s).` then `added=8 skipped=0`.

Fresh installs need none of this: `flask init-db` runs `create_all` + `seed_all`.

---

## Tests
`tests/test_p3_parameters.py` (5): distillation seeds carry their parameters;
parameters copy reaction-step → run (value empty); the insert route copies a
template's parameters into a reaction step; the run-fill route records a value
and is blocked once the run is completed; the run PDF builds with recorded
parameters.

`tests/test_p2b_procedures.py` updated: the seed-count assertions now use
`len(PROCEDURES)` (8) instead of a hardcoded 4, since P3 added four procedures.

Full suite: **631 passed**, 16 skipped. The 9 sandbox failures are the usual
RDKit-only ones — not regressions. Expect green on CI.
