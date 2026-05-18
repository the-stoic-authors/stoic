# Changelog

All notable changes to Stoic are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and Stoic adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Preparing v1.0.0. Planned: cross-platform installers (macOS,
Linux, Raspberry Pi), CI on GitHub Actions, contributor onboarding,
first stable release.

## [0.9.0] — 2026-05

First public open-source release. Stoic moves from a private project
to a public AGPLv3 repository.

### Added

- **AGPLv3 license** with full text in `LICENSE`
- **Contributor License Agreement** (`CLA.md`) with dual-licensing
  grant — lets contributors keep copyright while authorizing
  potential future commercial relicensing
- **Public README** with screenshots, install instructions, feature
  overview, and project status
- **`CONTRIBUTING.md`** with contribution workflow, code style,
  translation guide, test requirements, and CLA notice
- **`pyproject.toml`** updated with AGPLv3 license, PyPI
  classifiers, project URLs, and v0.9.0 version bump
- Copyright header in `stoic_eln/__init__.py`

### Changed

- Version bumped from `2.0.0a1` (internal alpha numbering) to
  `0.9.0` (preparing v1.0.0 public release)
- Author metadata changed from individual to `The Stoic Authors`

## [0.8.x] — 2026-05 (internal — "Settimana 6")

Internal pre-public iteration, captured as a series of patches
labeled 14.0 through 14.6.3. Highlights:

### Patch 14.6.3 — Sidebar UI fixes

- Replaced two custom "filled" icons (`reactions-history`,
  `preparations-history`) with standard lucide-icons (`history`,
  `folder-clock`) for visual consistency with the rest of the
  sidebar
- Fixed CSS rule to apply to both `<i>` (pre-render) and `<svg>`
  (post-lucide createIcons swap) so icon sizing stays stable
- Fixed collapsed-sidebar overlap: when collapsed, the logo is
  hidden and the toggle button takes its place as the sole focal
  point — clicking it re-expands. No more visual collision
  between toggle and logo

### Patch 14.6.2 — Reaction clone bug with mixture-based step components

- Fixed `clone_for_editing()` in `services/reaction_clone.py`
  which silently dropped `mixture_id` when cloning a
  `ReactionStepComponent`. This caused an `IntegrityError` when
  trying to edit any reaction with a step that used a Mixture
  (e.g. an eluent like "EtOAc/PE 5:2" in chromatography)
- Added two regression tests in
  `tests/test_step_component_with_mixture.py`: one reproducing
  the bug, one for the symmetric Substance-based case

### Patch 14.6.1 — Passphrase store strings + CLI hints translations

- Wrapped passphrase source labels and descriptions in
  `lazy_gettext` (they were hardcoded Italian strings in
  `services/passphrase_store.py`, never picked up by Babel)
- Fixed two fuzzy-match translations: "Ferma Stoic" → "Stop
  Stoic", "Riavvia" → "Restart"
- 10 new entries added to the EN `OVERRIDES` dict

### Patch 14.6 — Serious translation audit + in-app documentation

- Discovered and fixed ~600 wrong English translations frozen
  from old `pybabel update` fuzzy matches. Examples:
  `Miscele→SMILES`, `Storico preparazioni→Run in setup`,
  `Densità (g/mL)→Quantity (mL)`, `Lotto prodotto→Byproduct`
  (semantically opposite!)
- New `scripts/override_en_translations.py` with 646 curated
  translations organized by UI area — sovrascrive forzatamente
  per evitare future regressioni da fuzzy match
- Added in-app documentation viewer at `/docs/`:
  - User manual accessible to all logged-in users
  - Admin and Developer manuals admin-only (403 otherwise)
  - Markdown rendered server-side with `markdown` library
    (fenced code, tables, TOC, sane lists)
  - Sticky TOC sidebar with auto-generated anchors
  - IT↔EN toggle per manual
- Added `Documentazione` link to sidebar (visible to all)
- 15 new tests in `tests/test_docs.py`

### Patch 14.5 — Translation audit v1 + 6 manuals

- Wrote 6 user/admin/developer manuals (Italian + English),
  ~2800 lines total, in `docs/{it,en}/`
- First-pass translation audit: 459 errors corrected
  (149 wrong + 113 empty in Italian, 84 in Italian + 113 empty
  in English)
- New `scripts/heal_it_translations.py` (IT source language:
  msgstr = msgid always) and `scripts/heal_en_translations.py`
  (EN_FIXES dict with 220 manual translations)

### Patch 14.4 — Attachments on mixtures and preparations

- Extended attachments support to `Mixture` and `MixturePrep`
  entities. The attachment system was already implemented in
  patch 10 (polymorphic model with SHA-256 dedup); this patch
  adds the two missing entity types to `ATTACHMENT_ENTITY_TYPES`
  and wires up the UI in `preps/detail.html`

### Patch 14.3 — Passphrase source pluggable (none / prompt / file / env)

- 4 passphrase modes selectable in
  `Settings → Encryption & backups → Passphrase source`:
  - `none`: encryption disabled (default fresh install)
  - `prompt`: passphrase asked on every Stoic startup, kept in
    RAM only (max security)
  - `file`: stored in `instance/backup.key` (default after first
    enabling)
  - `env`: read from `STOIC_BACKUP_PASSPHRASE` env var (for
    systemd / Docker secrets)
- Architectural fix: `create_app(instance_path=...)` for test
  isolation; SQLCipher boot hook properly pushes app_context
- CLI command `flask passphrase-test` for verifying configuration
- Conftest fixture isolation with `tmp_path_factory.mktemp`

### Patches 14.0–14.2 — Encryption infrastructure

- 14.0: Automatic nightly backups via APScheduler with
  configurable hour/minute/retention. Manual backup via
  `flask backup`
- 14.1: AES-256-GCM encryption for backups with Argon2id KDF.
  Output format: `.db.gz.enc`. UI to enable/disable in Settings.
  Encrypted backups safe to copy to untrusted cloud storage
- 14.2: SQLCipher integration for live database encryption.
  AES-256-CBC + HMAC-SHA512 at page level. `flask db-encrypt`
  and `flask db-decrypt` CLI commands. Boot hook detects
  encrypted DB and prompts for passphrase as configured

## [0.7.x and earlier] — 2024-2025 (internal)

Internal development iterations before the public release. Major
milestones include:

- **Settimana 5** — PDF generation: per-batch labels (Avery
  L7160/L7164, Brother QL/Dymo thermal), per-substance SDS,
  per-run report PDFs, audit log CSV/PDF export
- **Settimana 4** — Orders module: plan/order/receive workflow,
  shopping list, auto-creation of inventory lots on receipt
- **Settimana 3** — Mixtures as first-class entities:
  preparations from precursor lots, mixture-based reaction
  components, eluent tracking for chromatography
- **Settimana 2** — Reaction templates with stoichiometric
  components, versioning (draft → publish → archive), embedded
  procedures, workup and checklists
- **Settimana 1** — Core entities: User, Substance, InventoryItem,
  Reaction, Run, with multi-language UI (IT/EN) and Bootstrap 5
  responsive layout. PubChem import for substances. GHS
  pictograms and H/P phrases. Audit log for all mutations

---

*For the full per-patch development history, see the individual
`PATCH-NOTES.md` files in the corresponding tarball releases.
These are preserved in the project's internal archive but not
included in the public repository.*
