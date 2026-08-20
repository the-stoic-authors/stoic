# Changelog

All notable changes to Stoic are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and Stoic adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- Inventory decrement for mixture-as-component preparations
  (e.g. preparing HCl 6N consumes a lot of HCl 12N)
- Docker multi-arch arm64 image (Raspberry Pi 4 support)
- Solvent recovery (green chemistry): recover solvent at run
  completion into separate recovered-solvent lots, with a
  worst-case use counter and a soft per-run reuse limit

## [1.4.4] — 2026-08-20

### Fixed

- Step components (workup, extraction, chromatography) now decrement
  the inventory lot they are bound to. Until now their quantities were
  counted by the run cost report but never removed from stock, so a
  column eluent had a price and no consumption.

### Changed

- Step consumption is reconciled incrementally: each component
  remembers how much it has taken and from which lot, so raising a
  quantity deducts only the difference, lowering it returns the excess,
  swapping the lot moves the deduction, and clearing the field gives
  everything back. Draft runs still hold nothing — deduction starts at
  *Avvia*, matching the main components.
- A lot that cannot cover a step quantity is clamped at zero and
  reported as a warning: the quantity is recorded anyway, because at
  that point it already happened at the bench.
- Migrations that add columns can now ship as Flask commands
  (`flask migrate-step-deduction`), which — unlike `scripts/` — are
  present inside the Docker image.

### Migration

- `run_step_component` gains `deducted_lot_id`, `deducted_mass_g` and
  `deducted_volume_mL` (all nullable). Run
  `flask migrate-step-deduction` (or
  `python scripts/migrate_step_deduction.py`) on an existing database:
  `ensure-schema` creates missing tables, never missing columns.

## [1.4.3] — 2026-08-03

### Documentation

- User manual (IT/EN): documented the PubChem *Draw* tab and the
  candidate disambiguation list; documented the per-product
  *Save to inventory* switch (products on, byproducts off, excluded
  from yield) with the HCl/NaHSO₄ example.
- How-to (IT/EN): added "Search for a substance by drawing its
  structure" and "Exclude a scrap from inventory" workflows.

## [1.4.2] — 2026-08-03

### Fixed

- The *Save to inventory* switch still returned 400 ("CSRF token
  missing"): as a bare checkbox outside a `<form>`, its HTMX POST
  carried no CSRF token. Added `hx-headers` with `X-CSRFToken`, the
  same pattern already used by the run-code / prep-code inline
  toggles. The switch now persists.

## [1.4.1] — 2026-08-03

### Fixed

- The *Save to inventory* switch on products/byproducts did not
  persist. The HTMX request used a `js:`-evaluated `hx-vals` reading
  `event.target.checked`, which failed to serialise the `field`
  parameter and made the endpoint return 400. Switched to a static
  `hx-vals` with the checkbox value included natively (unchecked =
  no value = not tracked), matching the other inline-edit controls.

## [1.4.0] — 2026-07-19

### Added

- **Per-product inventory flag** — each product/byproduct in a
  reaction now has a *Save to inventory* toggle. Products default to
  on (they are what you make); byproducts default to off (usually
  waste — e.g. NaHSO₄ from HCl generation, which you don't want
  filling the inventory). Components excluded from inventory are also
  excluded from the yield: the yield is on the product, not on the
  scraps. The flag can be turned on for genuinely recoverable
  byproducts.

### Migration

Adds column `track_in_inventory` to `reaction_component` and
`run_component`. Run once after pulling:

```
.venv/bin/python scripts/migrate_track_in_inventory.py
```

Existing rows (including existing byproducts) keep the historical
behaviour (tracked); the byproduct-off default applies only to newly
added components.

## [1.3.0] — 2026-07-19

### Added

- **Draw-to-search structure input for PubChem import** — the import
  page now has two tabs: *Text* (the existing name / CAS / SMILES /
  InChI / InChIKey / CID search) and *Draw*. The Draw tab embeds the
  JSME molecule editor; the drawn structure is converted to SMILES in
  the browser and searched on PubChem through the existing import
  flow. JSME (BSD-licensed, Novartis/Bruno Bienfait) is bundled
  locally under `static/lib/jsme/` and loaded lazily only when the
  Draw tab is opened, so the server works fully offline and the text
  search is unaffected. The JSME editor is framed as a light drawing
  canvas (its toolbar icons are baked light-on-nothing and have no
  recolour API, so it stays in its readable light look regardless of
  Stoic's light/dark theme).

## [1.2.1] — 2026-07-19

### Fixed

- PubChem candidate list never appeared: name searches resolved only
  the canonical match (`name_type=complete`), always yielding a single
  result. The candidate resolver now broadens the search with
  `name_type=word` and keeps only CIDs whose molecular formula equals
  the canonical match — i.e. genuine isomers and stereoisomers (all
  C6H12O6 for "glucose": α/β anomers, open-chain form, isotopologues,
  …), with the canonical compound listed first.

## [1.2.0] — 2026-07-18

### Added

- **PubChem multi-candidate import** — when a search returns more
  than one matching compound (e.g. isomers, salts, stereoisomers of
  "glucose"), Stoic now shows a disambiguation page with each
  candidate's name, molecular formula, CID, and a drawn structure,
  instead of silently auto-selecting the first result. Unambiguous
  searches (a single CID, InChIKey, CAS) still go straight to the
  preview — no extra click. Candidate structures and metadata are
  fetched in a single batch PUG-REST call and drawn client-side with
  SmilesDrawer.

## [1.1.1] — 2026-07-18

### Fixed

- Sticky "Save / Cancel" card in the mixture edit form scrolled up
  behind the sticky app-header instead of stopping just below it.
  Replaced the inline `top: 1rem` override with a reusable
  `.stoic-sticky-actions` CSS class that offsets by the header
  height (`calc(56px + 1rem)`) and sits below the header z-index.

## [1.1.0] — 2026-06-30

### Added

- **Supplier contact book** (`/suppliers/`) — store supplier name,
  address, phone, email, website/order portal, and portal
  credentials (username/password, plain text — protected by disk
  encryption at the deployment level).

- **Supplier selection in orders** — the order form's Supplier
  field is now a dropdown sourced from the contact book, alongside
  the existing free-text field for one-off suppliers. Selecting a
  contact-book supplier shows a live panel with email, phone, and a
  direct link to the order portal.

- **Orders grouped by supplier** — a supplier's detail page lists
  every linked order regardless of status, making it easy to spot
  when several lab members need reagents from the same supplier and
  consolidate into a single purchase order.

- **Mass concentration preparation strategy** — `suggest_consumptions`
  now handles mixtures where solutes have `g/L` or `mg/mL`
  concentrations (e.g. NaCl 400 g/L brine). The service calculates
  mass = concentration × target volume for each solute, and proposes
  the full target volume as "bring to volume" (qsp) for solvents
  with no explicit concentration. Previously these recipes fell
  through to the manual fallback.

- `Order.supplier_id` — nullable foreign key to `Supplier`,
  additive and backward compatible with the existing free-text
  `Order.supplier` field. No migration needed; the table is created
  automatically via `ensure-schema` on first run after upgrade.

### Fixed

- `Supplier.orders` relationship returned `None` instead of an empty
  list due to a bare `Mapped[list]` annotation (without type parameter)
  confusing SQLAlchemy 2.0's `uselist` inference. Fixed by using
  `Mapped[list["Order"]]` with explicit `uselist=True`.
- `log_event()` called with positional arguments in the suppliers
  blueprint; the function signature requires keyword-only arguments.
- Hardcoded Italian strings in `prep_service.py` warnings and
  `ValueError` messages now use English, fixing display in the EN
  locale.
- `Order.supplier_id` column missing from existing databases on
  upgrade; the column must be added via `flask ensure-schema` or
  the manual `ALTER TABLE` command documented in the upgrade notes.

### Documentation

- User manual (IT/EN): new "Supplier contact book" section; mixture
  preparation section expanded with automatic calculation strategy
  table (dilution, mass concentration, ratio/%).
- How-to guide (IT/EN): three new supplier workflows; preparation
  workflow updated with mass concentration example (brine recipe).

## [1.0.0] — 2026-06-27

First stable release. Stoic is now a fully self-hosted lab server:
one machine in the lab runs Stoic, everyone connects from their
own device (laptop, tablet, phone). The single-user desktop mode
remains supported but is no longer the primary deployment target.

### Added

- **Self-hosted server deployment** — Docker Compose stack (Stoic +
  Caddy) with automatic HTTPS via Caddy's local CA for `.local`
  domains and Let's Encrypt for public domains. One-line installer
  for Debian/Ubuntu: `curl -fsSL .../install-linux.sh | bash`.

- **gunicorn production server** — replaces `flask run` in
  production. Worker count, timeout, and bind address configurable
  via env vars (`STOIC_WORKERS`, `STOIC_TIMEOUT`, `STOIC_BIND`).
  Background scheduler runs in the gunicorn master process only.

- **Procedure library** (`/procedures/`) — lab-wide reusable step
  templates (flash chromatography, extraction, recrystallization,
  distillation). Inserting a procedure into a reaction protocol
  copies it (editing the library never touches historical protocols).

- **Step parameters** — typed process measurements (temperature,
  pressure, column head temperature, etc.) attached to reaction
  steps, propagated to run steps, and printed in the run PDF.
  Editable at any time during a run.

- **Step components: free-entry** (`free_name` / `free_unit`) —
  off-inventory items (filter paper, molecular sieves, sand) usable
  in step components without a substance record.

- **Standard procedure seed** — 8 built-in procedures: flash
  chromatography at 30/50/100 g silica per g compound (Still
  geometry, column diameter calculated automatically), standard
  aqueous/organic extraction, recrystallization, simple distillation,
  vacuum distillation, short-path distillation.

- **Add step to active run** (`POST /runs/<id>/step/add`) — add a
  step to a draft or in-progress run. Two modes: free step or clone
  from procedure library (copies components, checklist, parameters).

- **Global search Cmd+K** — modal palette across 8 entity types.
  Live results as you type. Cmd+K (macOS) / Ctrl+K (other).

- **Bench mode** — tablet-optimised layout for run execution.
  Sidebar hidden, larger tap targets, larger font. State persisted
  per run.

- **PWA support** — installable from Chrome on iOS/iPadOS, Android,
  and desktop. (Safari iOS on `.local` domains has a known WebKit
  cookie limitation; use Chrome on iOS.)

- **Off-site backup copy** — after every successful backup, Stoic
  copies the file to a configurable mount path. Failed copy shows
  a warning but never aborts the local backup.

- **How-to guide** (`/docs/howto`) — 14 quick-reference workflows
  in Italian and English: substances, PubChem import, orders,
  inventory, mixtures, preparations, reaction templates, procedures,
  runs, backup, lot labels, global search.

- **`WTF_CSRF_SSL_STRICT` configurable** via env var — set to
  `false` for `.local` deployments.

- **ProxyFix middleware**, **`/healthz` endpoint**, **`flask init-db`**
  command, **version string** in sidebar footer and `/healthz`.

### Fixed

- `_docs_root()` in production: fallback to `/app/docs` (Docker).
- `docs/` missing from Docker image (404 on all doc pages).
- TOC overlay on narrow screens in the documentation viewer.
- Caddyfile `email ""` causing Caddy startup failure on `.local`.
- Installer pulling source build context instead of ghcr.io image.
- Backfill logic moved to `services/` (importable from package).

### Changed

- `BackupFile` dataclass gains `offsite_ok: bool | None` field.
- `run_setup.py` gains `clone_template_step_to_run()`.

### Documentation

- `README.md`: new section "HTTPS and the browser security warning".
- How-to guide added (`docs/it/come-si-fa.md`, `docs/en/how-to.md`).
- Docker install guide updated with stoichub walkthrough and CA trust.

### Test suite

692 tests passing on macOS Intel x86_64 with Python 3.12.


## [0.9.1] — 2026-05-25

Patch release with bug fixes for the reaction scheme rendering
and the component table template. No schema or API changes.

### Fixed

- **Reaction scheme: reagents now drawn LEFT regardless of
  equivalents.** Components with `role="reagent"` were
  previously routed above the arrow as text labels when their
  equivalents fell outside a 0.8–1.5 window. This was
  chemically wrong: even a 4 eq excess amine in an
  α-bromoketone amination is still a co-reactant, not a
  catalyst, and belongs with the substrate on the left of the
  arrow. The `0.8 ≤ eq ≤ 1.5` window has been removed; all
  reagents now go LEFT. Only true sub-stoichiometric species
  (catalyst, ligand, base, acid, oxidant, reductant, additive)
  render above the arrow as molecular-formula text in
  SciFinder/Reaxys style.

- **Components table: stray Jinja comment fragment no longer
  visible.** The Babel extraction-stub block in
  `_components_table.html` consumed the opening `{#` of a
  rules-of-rendering comment, leaving two orphan lines
  ("- is_draft=True → editable inputs...") rendered as plain
  text under the "Components" heading. The comment is now
  properly bracketed.

### Changed

- `Reaction.derive_scheme()` return shape: the legacy `agents`
  list has been split into `agents_drawn` (always empty in
  current logic, retained for backward compatibility with
  callers that referenced the field) and `agents_text` (the
  list shown above the arrow as formatted molecular formulas).
- Order status labels (`pianificato`, `ordinato`, `ricevuto`,
  `ricevuto parziale`, `annullato`) now use `lazy_gettext` so
  the badge text is translated at render time, not at module
  import.

### i18n

- 15 reaction role badges added to the `_components_table.html`
  Babel extraction stubs (`Limitante`, `SM`, `Reattivo`,
  `Reagente`, `Catalizzatore`, `Legante`, `Base`, `Acido`,
  `Ossidante`, `Riducente`, `Solvente`, `Additivo`,
  `Std interno`, `Prodotto`, `Sottoprodotto`) and translated
  in the EN `.po` (`Limiting`, `SM`, `Reactant`, `Reagent`,
  `Catalyst`, `Ligand`, `Base`, `Acid`, `Oxidant`, `Reductant`,
  `Solvent`, `Additive`, `Int. std`, `Product`, `Byproduct`).
  These badges are picked from a Jinja dict via a runtime
  variable (`_(badge_text)`), which `pybabel extract` cannot
  see; the stubs make the literal strings visible to the
  extractor without producing output.

### Test suite

480 tests passing on Mac Intel x86_64.

## [0.9.0] — 2026-05-22

First public open-source release. Stoic moves from a private
single-author project to a public AGPLv3 repository at
[github.com/the-stoic-authors/stoic](https://github.com/the-stoic-authors/stoic).

### Feature surface at v0.9.0

Stoic v0.9.0 is a complete, runnable Electronic Lab Notebook /
Laboratory Inventory Management System for a small chemistry lab.
What's in:

- **Substances catalogue** with GHS pictograms, H/P phrases,
  CAS number, SMILES, InChI, IUPAC name, density, melting/
  boiling points, state of matter. PubChem import for one-click
  fill-in.
- **Inventory of lots** linked to substances and mixtures, with
  expiry tracking, cost, supplier, batch code, location,
  active/inactive flag, low-stock alerts.
- **Mixtures** as first-class entities (eluents, buffers,
  reagent solutions). Components can be substances or other
  mixtures (HCl 6N from HCl 12N stock). Hazards propagate
  derivatively from components with override capability.
- **Reactions** as versioned templates: header (title, procedure,
  temperature, duration, atmosphere, pressure), components
  (substance OR mixture, role, equivalents), step components
  (workup additions with ratio kinds: eq, mL/g, mL/mmol, %v/v,
  absolute mL, absolute g). Reaction schemes rendered as SVG
  from SMILES.
- **Runs** of reactions at user-chosen scale, with derived
  hazard pictograms, per-component lot picking from inventory,
  output lot creation on successful completion.
- **Mixture preparations** workflow: precursor lot consumption,
  imputed cost calculation, output lot creation with derived
  expiry (earliest among precursors), per-batch label printing.
- **Orders** plan/order/receive workflow with auto-creation of
  inventory lots on delivery, shopping list across pending
  orders.
- **Spending reports** at week / month / quarter / year buckets
  with date-range filters and visual distribution.
- **Encrypted backups** with AES-256-GCM and Argon2id KDF.
  Live database optional SQLCipher encryption. Pluggable
  passphrase sources: none, prompt, file, env var.
- **Audit log** of all entity mutations with PDF/CSV export.
- **PDF artifacts**: per-batch labels (Avery L7160/L7164,
  Brother QL/Dymo thermal), per-substance SDS, per-run report,
  audit log report.
- **Cross-platform CLI** `stoic` for daemon installation,
  startup, status, stop, update. macOS launchd + Linux
  systemd-user service generation.
- **One-shot installers** for macOS (`install-macos.sh`) and
  Debian/Ubuntu/Raspberry Pi (`install-linux.sh`).
- **In-app documentation viewer** at `/docs/` with 6 manuals
  (user, admin, developer × IT/EN), sticky TOC, IT↔EN toggle.
- **Multi-language UI** Italian (source) + English with curated
  translation overrides (646 entries) to avoid Babel fuzzy-match
  regressions.
- **Test suite**: 480 tests, 100% passing on macOS Intel x86_64
  with Python 3.12. Suite runs in ~2 minutes.

### Added

- **AGPLv3 license** with full text in `LICENSE`
- **Contributor License Agreement** (`CLA.md`) with dual-licensing
  grant — contributors keep copyright while authorising potential
  future commercial relicensing
- **Public README** with screenshots, install instructions, feature
  overview, project status, contact info
- **`CONTRIBUTING.md`** with contribution workflow, code style,
  translation guide, test requirements, CLA notice
- **`pyproject.toml`** with AGPLv3 license, PyPI classifiers,
  project URLs pointing to the public GitHub repo
- Copyright header in `stoic_eln/__init__.py`
- **macOS installer** (`scripts/installers/install-macos.sh`)
  one-shot from `curl | bash`: Homebrew + python@3.12 + cairo +
  pkg-config + clone + venv + init-db + first admin
- **Linux installer** (`scripts/installers/install-linux.sh`)
  same flow for Debian/Ubuntu/Raspberry Pi OS, both Intel and ARM
- **Git init helper** (`scripts/installers/init-git-repo.sh`) for
  setting up the local git repo with sensible defaults and the
  canonical author identity

### Fixed (since pre-release patches)

- **Step component absolute_mL and absolute_g** — the UI offered
  these ratio kinds but the calculator returned `None`. Now
  properly computes fixed mL or g amounts independent of scale
- **PDF text extraction in test helper** for macOS Intel — added
  zlib + ASCII85 decoding for compressed PDF streams (was
  reading only raw bytes, which failed when the PDF was
  compressed)
- **Suggested expiry pre-fill** in the manual-lot form: when
  creating a lot of a mixture, the form now pre-fills the
  expiry date from the earliest expiry of the component lots
- **Sidebar duplicate "Report" entry** removed; "Magazzino" → "Gestione"
- **`ngettext` with explicit `n=...` kwarg** in the spending report
  template (was raising KeyError when missing-cost count > 0)

### Test suite

480 passed in ~2 minutes on macOS Intel. Coverage spans:

- Authentication and authorisation
- Models (substances, mixtures, lots, reactions, runs, preps,
  orders)
- All blueprint routes
- Reaction step component calculation (eq, mL_per_g, mL_per_mmol,
  percent_vv, absolute_mL, absolute_g)
- Mixture-as-component recursion with cycle guard
- Spending report bucketing (week/month/quarter/year) and filters
- Encrypted backups round-trip
- SQLCipher database encryption
- PubChem import (real and mocked)
- PDF generation (labels, SDS, run reports, audit log)
- Document viewer rendering
- I18n: Italian source + English overrides + plural forms

### Internal milestones rolled up into v0.9.0

The path to v0.9.0 spanned roughly seven "weekly iterations"
internally, each a tarball-based patch series:

- **Settimana 1** — Core entities (User, Substance, InventoryItem,
  Reaction, Run), Bootstrap 5 responsive layout, multi-language
  UI scaffold, PubChem import, GHS pictograms, audit log
- **Settimana 2** — Reaction templates with stoichiometric
  components, versioning (draft → publish → archive), embedded
  procedures, workup and checklists
- **Settimana 3** — Mixtures as first-class entities, preparations
  from precursor lots, mixture-based reaction components, eluent
  tracking for chromatography
- **Settimana 4** — Orders module: plan/order/receive workflow,
  shopping list, auto-creation of inventory lots on receipt
- **Settimana 5** — PDF generation: per-batch labels, per-substance
  SDS, per-run reports, audit log CSV/PDF export
- **Settimana 6** — Encryption infrastructure: encrypted backups
  (AES-256-GCM + Argon2id), SQLCipher live database encryption,
  pluggable passphrase sources. Plus: in-app docs viewer with 6
  manuals, full translation audit fixing ~600 wrong English
  fuzzy-matches
- **Settimana 7** — Public release prep: AGPLv3 + CLA, cross-platform
  CLI (`stoic`), macOS and Linux installers, mixture-as-component
  schema, derived expiry, cost imputation, spending report, fix
  of 6 legacy test fails, hotfix for ASCII85+Flate PDF parsing on
  macOS Intel. **Stoic published to GitHub.**

---

For per-patch development history, see the `PATCH-NOTES.md` files
distributed with each tarball release during the development
phase. These predate the public repository and are not included
in it.
