# Hotfix — Edit/Publish a protocol with a free-entry step component

## The crash
Clicking **Edit** on a published protocol that contains a free-entry step
component (e.g. the flash-chromatography "Column Ø", `ratio_kind =
column_diameter_mm`) raised:

```
CHECK constraint failed: ck_reaction_step_component_substance_xor_mixture
```

## Why
A free-entry step component has no substance and no mixture — only `free_name`
(its XOR field). Both copy paths in `reaction_clone.py` were written before
free entries existed and didn't copy `free_name`/`free_unit`:

- `clone_for_editing` (Edit) dropped `free_name`/`free_unit` → the cloned
  component had **none** of the three XOR fields set → CHECK failure. This is
  the crash you saw.
- `promote_draft` (Publish) was worse: it dropped `mixture_id`, `free_name`,
  `free_unit`, `concentration_M` and `notes` — so even after fixing Edit, the
  crash would have reappeared at Publish time (and mixture-based step
  components would have silently lost their mixture).

Same class of bug as the P2b `run_step_component` 3-way XOR fix, on the
reaction-template side this time.

## Fix
Both blocks now copy the full set of XOR + data fields: `substance_id`,
`mixture_id`, `free_name`, `free_unit`, `concentration_M`, `notes`.

No schema change, no migration. The failed Edit rolled back cleanly, so no DB
data was corrupted — Edit just works now.

## Files
- `stoic_eln/services/reaction_clone.py` (both copy blocks)
- `tests/test_clone_free_components.py` (new): Edit and Publish round-trip of a
  protocol with a free-entry component, asserting `free_name`/`free_unit`
  survive both.

Independent of the v1-prep bundle (it doesn't touch `reaction_clone.py`), so it
applies cleanly whatever your current state.

## Apply
```bash
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-clone-free-component-fix.tar.gz -C ~/Projects/
make run
```

Then re-try Edit on that protocol — it should open the draft normally.

Full suite: **638 passed**, 16 skipped (9 sandbox RDKit-only failures, not
regressions).
