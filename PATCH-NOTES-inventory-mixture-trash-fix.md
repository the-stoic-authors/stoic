# Fix — Trash icon on a mixture lot in inventory crashed (BuildError)

## The crash
Clicking the trash icon on a **mixture** lot in the inventory page raised:

```
BuildError: Could not build url for endpoint 'substances.detail'.
Did you forget to specify values ['substance_id']?
```

## Why
The trash icon posts to `/inventory/<id>/deactivate` (a soft delete —
`is_active = False`). Both `deactivate` and `reactivate` redirected
unconditionally to `substances.detail` with the lot's `substance_id`. A mixture
lot has `mixture_id` and **no** `substance_id` → `substance_id=None` → the URL
can't be built → 500.

## Fix
Both routes now redirect to the owner's detail page based on the lot type —
the same pattern already used elsewhere in the file:

```python
if item.mixture_id:
    return redirect(url_for("mixtures.detail", mixture_id=item.mixture_id))
return redirect(url_for("substances.detail", substance_id=item.substance_id))
```

## Files
- `stoic_eln/blueprints/inventory/routes.py` (`deactivate` + `reactivate`).
- `tests/test_inventory_deactivate_redirect.py` (new): mixture lot
  deactivate/reactivate redirect to the mixture page; substance lot still
  redirects to the substance page.

No schema, no migration. Independent — applies on top of anything.

## Apply
```bash
cd ~/Projects/stoic-eln
tar -xzvf ~/Downloads/stoic-inventory-mixture-trash-fix.tar.gz -C ~/Projects/
make run
```
