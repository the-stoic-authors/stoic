# Stoic ELN — User manual

Stoic is an electronic lab notebook (ELN) for chemists. It tracks
substances, batches, reactions and runs, computes stoichiometry
and yields, and generates labels and PDF reports.

This manual is for lab users (people running reactions). For
configuration and user management see the administrator manual;
for code modifications see the developer manual.

---

## Key concepts

Stoic distinguishes five core entities. Understanding them is
half the work:

**Substance.** A chemical species in the lab catalog: acetic acid,
NaH, EtOAc, etc. One substance per InChIKey — no duplicates. Has
physical properties (MW, density, state), safety data (GHS, H/P
phrases), and identifiers (CAS, SMILES, IUPAC).

**Batch** (`InventoryItem`). A physical bottle of a specific
substance, with a batch code, remaining quantity, expiry date,
supplier, cost. A substance can have many batches (opening the
fifth jar of NaH? that's a new batch).

**Mixture** (`Mixture`). A physical preparation made of one or
more substances: solution (HCl 1N), eluent (EtOAc/Hexane 1:1),
buffer (PBS pH 7.4). Mixtures also have batches (see below) and
can be used in reactions as reagents.

**Reaction** (template). A generic "recipe": SM + reagents →
product, with stoichiometric coefficients, reference scale, and
procedure. It's the *template*, not a specific execution. A
reaction can be executed many times (runs).

**Run**. A single execution of a reaction. Specifies actual
scale, batches used, measured weights, yield, notes. Immutable
once completed (except for additive things like notes).

---

## Start here — first login

When an administrator creates your account, you get a username
and a temporary password. On first login Stoic asks you to
change it:

1. Open Stoic in the browser
2. Login with username + temporary password
3. Go to **Profile → Change password** (top right)
4. Set a password of at least 8 characters

From here you're operational. The dashboard shows: alerts
(substances below threshold, batches expiring), recent runs,
statistics.

---

## A typical lab day workflow

Concrete example: you want to run a Fischer esterification.

### 1. Check substance and batch availability

Go to **Substances** in the sidebar. Search for the carboxylic
acid, methanol, the catalyst. For each, check:

- **Is it in the catalog?** If not, add it (see below)
- **Do you have a batch with sufficient quantity?** Open the
  substance page, see the batches listed with remaining quantity
  and expiry

If a substance is missing from the catalog, click **New substance**.
You have two options:

- **Import from PubChem**: two modes on the same page.
  - *Text*: paste CAS, name, SMILES, InChI, InChIKey, or CID; Stoic
    pulls down properties, GHS, and identifiers. If the name is
    ambiguous (e.g. "glucose"), Stoic shows a list of candidates with
    their drawn structures, so you pick the right isomer at a glance
    instead of blindly taking the first hit.
  - *Draw*: open the **Draw** tab and build the molecule in the
    editor. Stoic generates the SMILES and searches PubChem for it.
    Handy when you know the structure but not the exact name.
  Always verify the downloaded data before saving.
- **Manual entry**: fill in fields by hand. Useful for compounds
  not in PubChem (synthetic intermediates, custom substances).

If a batch is missing, go to **Inventory** → **New batch** and
register it (purchase date, quantity received, expiry, supplier,
cost).

### 2. Create or find the reaction template

Go to **Reactions**. If the transformation already exists as a
template (someone has done it before), open it. Otherwise
**New reaction**:

- Descriptive title: "Fischer esterification with MeOH"
- Short code (e.g. `EST-MEOH`): auto-generated, you can
  customise it
- Reaction SMILES (optional): `O=C(O)CCC>>O=C(OC)CCC` for
  example. Stoic will derive the visual scheme from this if
  populated.
- Add **components**: substance, role (SM/reagent/product/
  solvent/catalyst/other), equivalents, and for each whether it's
  fixed in g or mL or free (`quantum satis`, typical for
  chromatography solvents)
- **Products and byproducts — "Save to inventory"**: every product
  and byproduct has an *Inventory* switch. When on, that component
  creates an inventory lot on run completion and counts toward the
  yield. **Products** are on by default (they are what you make);
  **byproducts** are off by default, because they are usually waste.
  Example: in HCl generation (NaCl + H₂SO₄ → HCl + NaHSO₄) you want
  the HCl in inventory, not the sodium bisulfate — otherwise the
  inventory fills up with NaHSO₄ on every run. A component excluded
  from inventory is also excluded **from the yield**: the yield is on
  the product, not on the scraps. If a byproduct is actually
  recoverable and you want to track it, turn the switch on.
- Add optional **steps** (procedure): "Dissolve SM in MeOH",
  "Add catalytic H2SO4", "Reflux 12 h", etc.
- Add **workup** and **checklist** if desired (routine actions
  to tick off during execution)
- **Publish** the reaction when satisfied. Only published
  reactions can be used for new runs.

### 3. Create the run

From the reaction page, click **New run**.

- **Scale**: choose a reference component (usually one with role
  SM) and a target quantity (e.g. 5 mmol). Stoic computes the
  amounts of all other components automatically.
- **Batches**: for each non-product component, pick the batch to
  draw from. Stoic only shows batches with sufficient quantity.
- **Real weights**: weigh the reagents, enter the actual measured
  g/mL values. Stoic recalculates moles and equivalents in real
  time.
- **Attachments**: you can upload photos of the setup, balance
  screenshots, before starting.

### 4. Start the run

When everything's ready, click **Start execution**. From here:

- The inventory is updated (batch quantities drop by the drawn
  amounts)
- Reagent weights become immutable (you can only modify products,
  notes, checklist)
- The run state moves from `draft` to `in_progress`

While the run is in progress, tick checklist items as you
complete them. Add free-form notes if needed (e.g. "TLC after 4h
still shows SM, extending reflux").

### 5. Complete the run

Once you've isolated the product:

- Weigh the product, enter the quantity in components with role
  Product
- Yield is computed automatically (mol product / mol SM × 100)
- Upload final attachments: NMR, HPLC, photo of the product
- Click **Complete run** at the bottom of the page

From here the run is immutable. Stoic automatically creates a
new batch of the product in inventory, with an auto-generated
code (e.g. `EST-MEOH-2026-001`).

### 6. Print the label

Go to the new batch in inventory, click **Print label**. Choose
format:

- **Avery L7160** (24 labels per A4 sheet, 63.5 × 33.9 mm) —
  compact format, fits on small bottles
- **Avery L7164** (12 labels per sheet, 63.5 × 72 mm) — more
  space, includes large molecular structure
- **Thermal 62 mm** (Brother QL / Dymo) — single label per page,
  ideal for thermal printers

Each label includes: substance name, IUPAC, batch code, expiry
date, CAS, formula, MW, density (if known), GHS pictograms,
H/P phrase codes, and a QR code that decodes to the batch URL
in Stoic.

Print as many copies as needed. For Avery you can choose "Start
at position N" if you're reusing a partially-used sheet.

---

## Workflow: preparing a mixture

Mixtures (solutions, eluents, buffers) are first-class entities
in Stoic. Example: you want to prepare 500 mL of HCl 1N from a
6N stock.

### 1. Create the mixture "recipe"

Go to **Mixtures** → **New mixture**:

- **Name**: "HCl 1N"
- **Type**: Solution
- **Primary concentration**: 1.0 N
- **Primary solvent**: Water (pick from the picker)
- Add **structured components** (optional): SM (hydrochloric
  acid) with concentration 1.0 N
- **Save**

Now "HCl 1N" is in the mixture catalog, but no physical batch
exists yet.

### 2. Run the preparation

From the mixture page, click **Prepare**. Enter:

- **Target quantity**: 500 mL
- **Precursor batches**: for each component, pick the batch to
  draw from. For HCl 6N, pick the batch in inventory.
- Stoic shows you **how much to draw from each** (for HCl 6N:
  500 mL × 1 N / 6 N = 83.3 mL)
- Confirm with **Execute preparation**

Stoic creates:
- A new batch of mixture "HCl 1N" with quantity 500 mL and a
  batch code (e.g. `HCL1N-2026-001`)
- Inventory update: the HCl 6N batch drops by 83.3 mL

From here you can use the new HCl 1N batch in reactions like any
other batch, and print labels from the created batch.

### Automatic calculation strategies

Stoic recognises three recipe types and calculates accordingly:

| Strategy | When triggered | Example |
|----------|---------------|---------|
| **Dilution** | Single solute + primary concentration set on the mixture | HCl 1N from HCl 6N |
| **Mass concentration** | One or more solutes with `g/L` or `mg/mL` units **and primary concentration left empty** | NaCl 400 g/L (brine) |
| **Ratio / %** | Components in `ratio`, `%v/v`, `%w/w` or `%w/v` | EtOAc/Hexane 3:7 |

> **Important**: the mixture's "Primary concentration" field should only be filled for **dilutions from stock** (e.g. HCl 1N from HCl 6N). For direct dissolution recipes (e.g. solid NaCl in water), leave it **empty** — otherwise Stoic will attempt a dilution instead of a mass calculation.

For **mass concentration** recipes (e.g. brine):
- Add the solute with role `Solute` and concentration `400 g/L`
- Add the solvent (water) with role `Solvent` and empty concentration
- Stoic will propose: **400 g of NaCl** + **1 L of water** to bring to volume

---

## Procedure library

Repetitive procedures (aqueous workup, celite filtration, flash
chromatography…) are saved once and reused everywhere.

**Saving**: in a draft protocol, every step has a library icon 📚
in its header. Click it, give it a name, save. Components and
checklist go into the lab-wide library.

**Reusing**: the "New step" modal of any draft protocol shows
"…or insert from the procedure library". Pick and insert: the
procedure is COPIED into the protocol.

**Editing**: the library is edited through a protocol: insert the
procedure, adjust it, re-save under the same name ticking
"overwrite". Protocols that used the previous version do NOT
change — each protocol keeps the copy it was built with, the same
way Runs freeze their templates.

The **Procedures** page in the menu shows the whole library, with
rename and delete (deleting from the library never touches
protocols).

## Free entries in steps

Besides substances and mixtures, a step can hold **non-inventory
entries**: the column diameter, celite, ice. In the "Add
component" form pick "Free entry", give it a name and a free
unit (mm, g, CV, whatever fits).

Quantity modes for free entries:

  - **fixed value** — a number in your unit ("Celite, 5 g")
  - **ad lib.** — no value in the template, recorded at Run time
  - **column Ø (bed h, cm)** — the diameter is COMPUTED: the
    value you enter is the silica bed height in cm (15 is the
    flash standard); Stoic finds the component with the
    "stationary phase" role in the same step, takes its mass at
    the Run scale and derives the diameter from cylinder geometry
    (silica bulk density 0.5 g/mL). The Run shows it as
    "suggested: 23 mm" — round to the column you own. Doubling
    the scale widens the diameter by √2, as it should.

## Attachments

Every run, reaction template, substance, batch, mixture, and
preparation can have attachments. Typical types:

| Entity | Attachment type |
|---|---|
| Run | NMR, HPLC, MS, setup photos, TLC photo, product CoA |
| Reaction (template) | SOP, annotated procedure, reference article |
| Substance | Supplier SDS, general CoA |
| Batch | Label, jar photo, batch-specific CoA |
| Mixture | Recipe SOP, photo of bottle |
| Preparation | Product CoA, setup photo, calibration |

**Accepted file types**: PDF, images (jpg/png/gif/webp), lab data
(csv, xlsx, jdx, mol, raw, mzML, etc.), .zip archives.

**Rejected types**: executables, HTML, JavaScript, SVG (for
security). Max 100 MB per file.

**Automatic dedup**: if you upload the same file (same content)
twice, Stoic recognises it via SHA-256 and keeps a single
physical file on disk, with two references.

**Deletion**: whoever uploaded the attachment can delete it.
Administrators can delete anyone's attachments. All operations
are tracked in the audit log.

---

## Workflow: order management

Stoic has a built-in orders module for planning and receiving
purchases.

### 1. Plan an order

From the substance page, click **Plan new order**. Enter:

- Quantity (g or mL, based on physical state)
- Supplier, catalog code, estimated cost
- Expected delivery date

The order enters `planned` status.

### 2. Confirm ordered

When you've placed the order with the supplier (phone, email,
corporate purchasing system), come back to the order and click
**Mark as ordered**. Status moves to `ordered`. From this point
you can no longer modify its details.

### 3. Receive the order

When the order arrives, click **Receive**. Enter:

- Quantity actually received (may differ from planned)
- Final cost (may differ from estimate)
- Supplier batch number
- Received date, supplier expiry

Stoic automatically creates a new `InventoryItem` (batch) with
these data. The order moves to `received`.

### 4. Shopping list

From the dashboard or the Orders menu, there's a **Shopping list**
view: all substances below minimum threshold, with suggested
quantity (threshold + 50% buffer), last supplier, and estimated
unit cost. Handy to print/copy for bulk orders.

---

## Supplier contact book

Since version 1.1, Stoic has a dedicated supplier contact book,
accessible from the **Suppliers** entry in the sidebar.

### What you can save

For each supplier: name, address, phone, email, website / order
portal, portal username and password, and free-text notes (payment
terms, sales contact, etc.).

> Portal username and password are stored in plain text in the
> database. On a self-hosted installation with disk encryption (as
> recommended for production deployments) this is an acceptable
> trade-off — it is still not a substitute for a dedicated password
> manager for high-risk credentials.

### Using a supplier in an order

When planning a new order, the **Supplier** field shows a dropdown
of suppliers in the contact book, plus a free-text field for
one-off suppliers not yet saved. Selecting a supplier from the
contact book shows a panel with email, phone, and a direct link to
the order portal — useful so you don't have to look up credentials
elsewhere while filling in the order.

### Orders grouped by supplier

From a supplier's detail page (click the name from the contact
book), you see all orders linked to that supplier, in any status.
This is useful when several people in the lab need reagents from
the same supplier: you can see everything planned and place a
single cumulative order instead of several separate ones with
multiple shipping costs.

---

## Dashboard and statistics

Stoic's home shows:

- **Alerts**: substances below threshold, batches expiring in
  the next 30 days, expired batches
- **Recent runs**: last 10 runs executed, sorted by date
- **Statistics**: total counts of substances/reactions/runs,
  average yields, most-used substances

From statistics you can also go to **Trends** to see consumption
graphs over time for each substance.

---

## What to do if…

**I entered a wrong weight after starting the run.** If the run
is still `in_progress`, reagent weights are frozen and you can't
modify them directly. You need to cancel the run (button at the
bottom) and repeat from scratch. Cancelling restores batch
quantities.

**I want to cancel a completed run (zero yield, lost product).**
You can't. Once completed, the run is permanent. You can add
notes ("Workup failed, product lost on column") and mark the
run as "failed" by creating a new identical run and completing
it with zero yield.

**I accidentally duplicated a substance.** Substances are
deduplicated by InChIKey: you can't create an exact duplicate.
If you have two records for the same molecule with different
InChIKeys (e.g. with/without isotopes), administrators can merge
them.

**A substance isn't in PubChem.** Add it manually. Strictly
required fields: name, formula, MW. SMILES and identifiers are
strongly recommended. You can leave GHS blank if you don't know
them (always check the supplier's SDS).

**I lost the backup passphrase.** If Stoic is configured in
`prompt` mode (passphrase only in your head), encrypted backups
are lost. Contact your administrator: they can restore a plain
state of the DB, but historical encrypted backups will not be
recoverable.

**The DB seems corrupted / Stoic won't start.** Contact your
administrator. There's almost always a recent backup to restore
from (in `instance/backups/`). Don't manually touch
`instance/stoic_eln.db` — that's a sysadmin operation.

---

## Language

Stoic supports Italian and English. Change language from the
user menu (profile). The preference is saved to your account.

---

## Light/dark theme

Toggle in the header. The preference is saved to your account.

---

## Keyboard shortcuts

- `Ctrl+K` (`Cmd+K` on Mac): open the global search bar
  (substances, reactions, batches, runs)
- `Esc` closes modal popups
- `Tab` navigates between form fields (standard browser)

---

## Data security

Stoic can protect lab data with three layers:

1. **Encrypted automatic backups** every night
2. **Live database encryption** (SQLCipher) — the
   `stoic_eln.db` file is opaque without the passphrase
3. **Passphrase in RAM only** — whoever takes the filesystem
   doesn't find the key

Configuration is up to the administrator. See the admin manual
for details.

---

## Audit log

All significant actions (create/edit/delete of substances,
reactions, batches, runs, attachment uploads) are tracked in
an audit log. Only administrators see the full log, but your
own records are always visible from your profile.

If you accidentally delete something (e.g. a substance), the
audit log contains the event. Ask the administrator to review.
