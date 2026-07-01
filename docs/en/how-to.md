# Stoic ELN — How To

Quick-reference guide for the most common workflows. Numbered steps, no theory.
For background concepts see the [User Manual](user-manual.md).

---

## Add a substance manually

1. Sidebar → **Substances** → **New substance**
2. Choose **Manual entry**
3. Fill in at minimum: name, molecular weight, physical state
4. Add CAS, SMILES, density if available
5. Under **Safety**: select GHS pictograms, enter H and P phrases
6. **Save**

> H/P phrases appear on lot labels — entering them now avoids
> coming back later.

---

## Add a substance from PubChem

1. Sidebar → **Substances** → **New substance**
2. Choose **Import from PubChem**
3. Paste a CAS number, IUPAC name or SMILES into the search field
4. Select the correct result from the list
5. Review the pre-filled data (MW, density, GHS)
6. Correct any errors (PubChem is not always accurate on density and state)
7. **Save**

> For synthetic intermediates not in PubChem, use manual entry.

---

## Order management

### Plan an order
1. Open the substance page → clic **Plan new order**
2. Enter quantity, supplier, catalogue code, estimated cost, expected date
3. **Save** → order status: `planned`

### Confirm the order was placed
1. Open the order → clic **Mark as ordered**
2. Status changes to `ordered` (no further edits allowed)

### Receive an order
1. Open the order → clic **Receive**
2. Enter: quantity received, final cost, supplier lot number, expiry date
3. **Confirm** → Stoic automatically creates an inventory lot

---

## Add a supplier to the contact book

1. Sidebar → **Suppliers** → **New supplier**
2. Enter name, address, phone, email
3. Add the website / order portal if available
4. If you have a portal account, enter username and password
   (stored in plain text — the server disk is encrypted)
5. **Add supplier**

> You can also create a supplier on the fly from the new order
> form, by clicking the "+" icon next to the supplier dropdown.

## Use a supplier from the contact book in an order

1. When planning an order, open the **Supplier** dropdown
2. Select the supplier from the contact book
3. A panel appears with email, phone, and a portal link —
   everything you need to place the order is right there
4. Fill in the rest of the form and **Save**

## See all orders for a supplier

1. Sidebar → **Suppliers** → click the supplier's name
2. The page shows contacts, portal credentials, and the full list
   of linked orders, in any status

> Useful when several people in the lab need to order from the same
> supplier: see everything planned and place a single cumulative
> order instead of multiple shipping costs.

---

## Add a substance to inventory (lot)

To add a lot without going through the order module (e.g. a reagent
already on the shelf):

1. Open the substance page
2. Clic **Add lot**
3. Enter: quantity, unit, supplier, supplier lot number, expiry date, cost
4. **Save**

The lot appears in the substance's inventory list and is available for runs.

---

## Create a mixture (recipe)

A mixture is a reusable recipe (e.g. 1N HCl, EtOAc/Hexane 3:7).

1. Sidebar → **Mixtures** → **New mixture**
2. Assign a descriptive name (e.g. `1N HCl aqueous`)
3. Add components: for each one, search the substance, enter the
   ratio (e.g. mL/L or % v/v) and the role
4. Add preparation notes if useful
5. **Save**

The mixture is now available as a reagent in reactions and procedures.

---

## Prepare a mixture (execution)

1. Open the mixture → clic **New preparation**
2. Enter the target volume (e.g. 1 L) and unit
3. Stoic automatically calculates quantities:
   - Solutes with `g/L`: mass = concentration × volume (e.g. 400 g/L × 1 L = 400 g)
   - Solvent with no concentration: full target volume (qsp, bring to volume)
   - Ratio or percentage mixtures: proportional split
4. Select the lots to use for each component
5. Physically prepare the mixture
6. Enter the actual quantity obtained
7. **Complete preparation**

Stoic creates a mixture lot usable in inventory and in runs.

---

## Add a mixture to inventory (lot)

To register a mixture lot prepared externally (e.g. a commercial
buffer, a received solution):

1. Open the mixture → clic **Add lot**
2. Enter: quantity, unit, preparation/reception date, expiry date
3. **Save**

---

## Create a reaction template

1. Sidebar → **Reactions** → **New reaction**
2. Assign a name (e.g. `Fischer esterification — acetic acid/methanol`)
3. Add components:
   - **Starting material**: the stoichiometric limit (1 eq)
   - **Reagents/Reactants**: enter equivalents relative to SM
   - **Catalysts, bases, acids**: enter eq or mol%
   - **Solvents**: enter mL/mmol
   - **Expected product**: enter theoretical equivalents (usually 1.0)
4. Add work-up steps (extraction, purification, analysis)
5. Clic **Publish** when the template is ready for use

> A draft template cannot be run. Publish only when the procedure
> is established.

---

## Save a procedure to the library

To save a work-up/purification step as a reusable procedure:

1. Open the reaction template containing the step
2. In the step header → clic **Save to library**
3. Assign a unique name (e.g. `Still flash chromatography — 30 g/g`)
4. **Save**

The procedure is now available to all templates in the lab.

---

## Use a procedure in a reaction

1. Open the reaction template in edit mode
2. Under **Steps** → clic **Add step from library**
3. Select the procedure from the list
4. The step is copied into the template (independently editable)

> Editing the library later does **not** change templates that have
> already copied the procedure. This is intentional: historical
> reproducibility is guaranteed.

---

## Run a reaction

### Create the run
1. Open the reaction template → clic **New run**
2. Stoic creates a draft with all components copied from the template

### Set the scale
1. In the run, enter the mass (or mmol) of the **starting material**
2. Stoic automatically recalculates all quantities

### Assign lots
1. For each component, select the lot from the dropdown
2. If a lot does not appear, check that the substance is in inventory
   with quantity > 0

### Start the run
1. Clic **Start run** — the run is now in progress
2. During execution you can:
   - Record actual weighed quantities
   - Add steps on the fly (clic **Add step** at the bottom)
   - Record process parameters (temperature, pressure, etc.)
   - Tick checklist items
   - Add execution notes

### Complete the run
1. Weigh the product and enter the mass in the **Product** row
2. Yield is calculated automatically
3. Add final attachments (NMR, HPLC, photos)
4. Clic **Complete run**

The run is now immutable. Stoic creates a product lot in inventory.

### Bench mode (tablet)
On a tablet at the bench: clic **Bench mode** in the run header.
The sidebar disappears, buttons enlarge, font size increases. Clic
**Exit** to return to normal view.

---

## Configure backup

### Automatic backup
1. Sidebar → **Settings** → **Backup**
2. Enable **Automatic backup**
3. Set the time (default: 03:00) and retention days
4. **Save configuration**

### Off-site backup (recommended)
1. Mount the external volume on the server (NAS, USB drive, disk) via
   `fstab` or `systemd.mount` — Stoic does not mount volumes itself
2. Under **Settings → Backup**: enable **Off-site copy**
3. Enter the mount path (e.g. `/mnt/nas/stoic-backups`)
4. **Save** → at the next backup Stoic copies the file there too

If the off-site copy fails, the local backup is already safe and a
yellow warning appears. The backup is never aborted due to an
off-site error.

### Manual backup
Under **Settings → Backup** → clic **Run backup now**.

---

## Print a lot label

1. Open the lot (from **Inventory** or from the substance page)
2. Clic **Print label**
3. Choose the format:
   - **Avery L7160** — 24 labels/A4 sheet, for small vials
   - **Avery L7164** — 12 labels/A4 sheet, large molecular structure
   - **Thermal 62 mm** — for Brother QL / Dymo printers
4. Open the PDF and print

The label includes: name, IUPAC, CAS, MW, batch code, expiry date,
GHS pictograms, H/P phrases, QR code linking to the lot in Stoic.

---

## Global search (Cmd+K)

To find any entity in the app in under two seconds:

1. Press **Cmd+K** (Mac) or **Ctrl+K** (Windows/Linux) from any page
2. Type a name, code or identifier
3. Stoic searches across: substances, mixtures, reactions, runs,
   orders, preparations, lots, notes
4. Click a result or use arrow keys + Enter to navigate

> Search is live: results appear as you type, no need to press Enter.
