# Patch P2b — Standard procedure library + `g_per_g` + run-step reference

Seeds the four starter procedures (3 flash + standard extraction) into the
StepTemplate library, adds the `g_per_g` mass-loading ratio kind they need,
and makes a run step honour its **reference component** (so flash silica
loading computes "g per g of crude" against the product, not the limiting
reagent). Along the way it fixes two latent P2 bugs that the new procedures
expose.

---

## What's in it

### 1. New ratio kind `g_per_g` (grams per gram of reference)
A pure mass:mass loading — no MW/density needed, and **g-only by design**
(converting silica to mL via its skeletal density would be meaningless; the
column-diameter calc applies a process bulk density separately).
- `models/reaction_step_component.py`: added to `RATIO_KINDS` + IT/EN labels.
- `services/step_calc.py`: new branch in `compute_step_component`.
- `templates/reactions/_step_card.html`: option added to both dropdowns
  (`g/g` is a unit label, like `mL/g`, so no translation entry needed).
- Route validation already checks against `RATIO_KINDS` → no route change.

### 2. Run step honours its reference component (the "B" decision)
`RunStep` did **not** snapshot the template step's reference, so run-time
calcs always fell back to the limiting reagent. Now:
- `models/run_step.py`: new nullable column `reference_run_component_id`
  (FK → `run_component`, `ON DELETE SET NULL`).
- `services/run_setup.py`: maps each reaction component to its `RunComponent`
  snapshot and freezes the step reference on the `RunStep`. Products are
  already snapshotted as run components, so pointing a flash step at the
  product gives `ref_g = scale × MW_product / 1000` = theoretical crude mass.
- `services/step_calc.py`: `compute_run_step_component` resolves the
  reference (snapshot if set, else limiting) and uses its own equivalents.
- The protocol-preview path (`_step_quantity`) already used the same
  resolution, so preview and run now agree.

### 3. Four seeded procedures
- `seeds/procedures.py` (new): declarative data.
  - **Flash facile / media / difficile** (`purification`): silica via
    `g_per_g` (30 / 50 / 100 g per g crude) + a free-entry **Colonna Ø**
    (`column_diameter_mm`, bed height 15 cm) + a free **Eluente** + TLC
    checklist. Each description tells you to set the step reference to the
    product and gives the eluent guideline (~mL/g, ~column volumes).
  - **Estrazione standard** (`extraction`): all ad-lib volumes (solvent 3×,
    NaHCO₃ sat., brine) + Na₂SO₄ (substance-backed, inventory-tracked) +
    checklist.
- `seeds/loader.py`: `seed_procedures()` — idempotent by `StepTemplate.name`,
  resolves substances by InChIKey, wired into `seed_all()` after substances.

**Note on "Chromatography Silica Gel":** intentionally NOT added. `g_per_g`
is a pure mass ratio (silica density irrelevant to the silica mass), and the
bed bulk density (0.5 g/mL) belongs as a process constant in the diameter
calc, not duplicated onto a substance row (a second SiO₂ would also collide
on the InChIKey de-dup). When alumina/C18 flash procedures arrive — different
bed densities — that's when bulk density should become editable data.

### 4. Two latent P2 bugs fixed (found while building the above)
- **`procedures/index.html` crash on free entries.** The library page did
  `c.mixture.name` on free-entry components (mixture is `None`) → 500.
  Fixed with a `free_name` fallback; also prettified the ratio display
  (`q.b.`, `Ø colonna (h N cm)`, `g/g`).
- **`run_step_component` 2-way CHECK.** P2 added `free_name`/`free_unit` to
  this table but left its CHECK at the old `substance ⊻ mixture` (its sibling
  tables got the 3-way XOR). On any `create_all`/`ensure-schema` database,
  launching a run with a free-entry step component (e.g. a Colonna Ø line)
  **fails at insert**. Fixed: model CHECK widened to 3-way; migration rebuilds
  the table.

---

## Migrations (both tested empirically on old-schema DBs)

Two migrations, both idempotent:

- `scripts/migrate_p2b_run_step_reference.py` — adds
  `run_step.reference_run_component_id` (plain nullable `ADD COLUMN`, **no**
  CHECK rebuild). Old runs get NULL = "use limiting reagent".
- `scripts/migrate_p2b_run_step_component_xor.py` — rebuilds
  `run_step_component` with the 3-way XOR CHECK (SQLite can't ALTER a CHECK).
  Preserves all rows + FKs, recreates the three indexes. Adds
  `free_name`/`free_unit` first if a pre-P2 DB somehow lacks them.

Plus a one-shot seeder for existing databases:

- `scripts/seed_procedures.py` — seeds the four procedures into an already
  initialised DB (`seed_all()` only runs at `flask init-db`). Idempotent.

---

## Apply

```bash
cd ~/Projects
tar -xzvf stoic-p2b-procedure-seeds.tar.gz -C ~/Projects/
cd stoic-eln

# 1) schema migrations (order doesn't matter; both idempotent)
.venv/bin/python scripts/migrate_p2b_run_step_reference.py
.venv/bin/python scripts/migrate_p2b_run_step_component_xor.py

# 2) seed the four procedures into your existing DB
.venv/bin/python scripts/seed_procedures.py

# 3) recompile catalogs already done in-patch; if you re-extract .po only:
.venv/bin/pybabel compile -d stoic_eln/translations

# 4) run
make run
```

Fresh installs need none of the above — `flask init-db` runs `create_all`
(correct 3-way CHECK + reference column) and `seed_all` (the four procedures).

---

## Tests
`tests/test_p2b_procedures.py` (9 tests): g_per_g mass-only; column geometry
(30 g silica, 15 cm bed → 22.57 mm); run-step snapshots the reference; silica
scales with the **product** when referenced (5 mmol × MW 200 → 1.0 g → 30 g
silica) and falls back to the limiting reagent when not; seed content +
idempotency; library page renders free entries without crashing.

Full suite: **625 passed**, 16 skipped. The 9 failures in the sandbox are the
usual RDKit-only ones (`test_molecule_svg` ×8, the L7164 structure-embed test)
— no RDKit installed here, not regressions. Expect green on CI.
