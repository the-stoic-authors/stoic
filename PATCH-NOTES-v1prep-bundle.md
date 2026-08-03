# Bundle — P3 (parameters + EN procedures) + Production cost report + i18n fixes

One tarball with the final state of three pieces of work that share files
(so they can't be applied separately out of order). Safe to apply on your
current P2b Mac in one go.

## What's inside

**1. P3 — recorded step parameters + EN procedures**
- Generic parameter model (template → reaction step → run), mirroring
  checklists; filled at run time, printed in the run PDF.
- 8 seeded procedures, now in **English**: 3 flash, standard extraction,
  recrystallization, 3 distillations (with pressure / head-T parameters).
- New tables `step_template_parameter`, `step_parameter`, `run_step_parameter`
  (additive → `make ensure-schema`, no migration script).

**2. Production cost report** (`Reports → Production costs`)
- Cost to make each in-house batch, per substance and per batch, **cumulative
  and direct** side by side; multi-product runs split by mass. No schema change.

**3. Translation fixes** (the items you listed)
- Sidebar + Docs page (title, subtitle, manual names); Dashboard "Suggested
  for re-order" / "Recent activity" colored labels; Runs history status
  labels; Mixtures search placeholder (was a wrong Italian string); single
  mixture "Safety (GHS)"; Audit log action labels; Backup passphrase-source
  descriptions + "Configuration".
- Mechanism: status / action / inventory labels are now `lazy_gettext` so they
  localize (audit, inventory, run); several entries were **fuzzy** in the EN
  catalog (msgfmt skips fuzzy → showed Italian) and are now de-fuzzed; ~55 EN
  strings added/corrected.
- Also fixed a latent bug: the locale selector dereferenced `current_user`
  outside a request → it now falls back to the default locale for PDF/
  background generation. (Regression test added.)

## Apply (once, in this order)

```bash
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-v1prep-bundle.tar.gz -C ~/Projects/

make ensure-schema
.venv/bin/python scripts/reseed_procedures.py
make translations
make run
```

- `make ensure-schema` → creates the 3 parameter tables.
- `reseed_procedures.py` → removes the 4 Italian seed procedures and seeds the
  8 English ones (`Removed 4 …` then `added=8 skipped=0`). Safe for protocols
  (procedures are copied into reactions, not referenced).
- `make translations` → recompiles the catalogs.

Fresh installs need none of this (`flask init-db` does it all).

## Tests
Full suite **634 passed**, 16 skipped — the 9 sandbox failures are RDKit-only
(no RDKit here), not regressions. New: `test_p3_parameters.py`,
`test_production_cost_report.py`, `test_i18n_labels.py`; `test_p2b_procedures.py`
updated for the English seed names + count.

## Still open (not in this bundle)
- Pre-existing duplicate msgids in the EN catalog for role labels
  ("Reattivo", "Base", "Solvente", …) — harmless (compile tolerates them) but
  worth a cleanup pass.
- Optional: a UI to add parameters to a step by hand (today they come only
  from seeded procedures).
