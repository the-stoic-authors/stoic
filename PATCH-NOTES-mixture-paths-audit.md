# Audit — substance-only assumptions on mixture / free-entry paths

A systematic sweep for the bug class we kept hitting: code written when lots
were *only* substances and components were *only* substances, which breaks for
**mixture lots** or **free-entry** step components.

## Fixed here
1. **Print-label page crashed for a mixture lot** (`templates/inventory/label_print.html`)
   The breadcrumb and subtitle dereferenced `item.substance` unconditionally →
   500 for a mixture lot (no substance). Now branches on the lot's owner
   (mixture → mixtures pages; substance → substances pages). The label **PDF**
   was already mixture-aware; only the HTML preview was broken.
2. **`ReactionStepComponent.display_name`** (`models/reaction_step_component.py`)
   Returned "—" for a free entry (no substance/mixture). Now returns
   `free_name`, mirroring the `RunStepComponent` fix. Currently dormant (the
   step-card template uses its own conditional), fixed for symmetry so a future
   caller can't reintroduce the blank.

## Swept and confirmed already safe (no change needed)
- `inventory/_list_table.html`, `inventory/form.html` — branch on mixture vs
  substance (`if mix` / `owner_kind`).
- `mixtures/detail.html`, `mixtures/_component_row.html`,
  `preps/detail.html` — guard component refs (`elif c.substance` / child
  mixture / free).
- `services/labels.py` — `sub.name if sub else mix.display_label` (PDF labels
  handle mixtures).
- `services/prep_service.py` — `lot.substance.name` is behind
  `if lot.substance is not None`.
- inventory `label_pdf` / `edit` routes — pass both `substance` and `mixture`
  to a guarded template; don't deref directly.
- `mixtures.delete` — soft-delete that refuses when active lots exist (no
  crash, graceful message).

## Already fixed earlier this session (not re-shipped here)
- `inventory.deactivate` / `reactivate` redirect for mixture lots.
- `clone_for_editing` / `promote_draft` carrying free-entry fields.
- Run PDF step quantities + free-entry names; the column-Ø role.
- Prepared mixtures carrying a production cost (+ backfill).

## Files
- `stoic_eln/templates/inventory/label_print.html`
- `stoic_eln/models/reaction_step_component.py`
- `tests/test_inventory_mixture_label.py` (new): label page renders for a
  mixture lot (and still for a substance lot).

No schema, no migration. Full suite **651 passed**, 16 skipped (9 sandbox
RDKit-only failures).

## Apply
```bash
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-mixture-paths-audit.tar.gz -C ~/Projects/
make run
```
