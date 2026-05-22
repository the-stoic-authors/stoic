# Changelog

All notable changes to Stoic are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and Stoic adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Path to v1.0.0. Planned (non-exhaustive):

- Live remediation of any v0.9.0 bug reports surfacing once the
  public install base grows
- "Plan order" workflow extended from Substance to Mixture
  (commercial mixtures like HCl 12N from Sigma)
- `prep_service` decrement of inventory for mixture-as-component
  preparations (e.g. preparing HCl 6N consumes a lot of HCl 12N)
- Additional connector ecosystem (Stoic ↔ eLabFTW import/export,
  ChemDraw/ChemAxon paste-in)

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
