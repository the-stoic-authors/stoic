<div align="center">

![CI](https://github.com/the-stoic-authors/stoic/actions/workflows/ci.yml/badge.svg)

# Stoic

**An open-source electronic lab notebook (ELN) for chemistry labs.**

Self-hosted · Multi-user · Audit-ready · AGPLv3

[![License: AGPL v3](https://img.shields.io/badge/license-AGPLv3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-414%2F420-green.svg)](#testing)
[![Version](https://img.shields.io/badge/version-0.9.0-orange.svg)](CHANGELOG.md)

[Documentation](docs/) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md)

</div>

---

## What is Stoic

Stoic is an electronic lab notebook (ELN) designed for chemists who
want to keep their workflow on their own hardware. It tracks
substances, batches, reactions, runs, mixtures, and orders, computes
stoichiometry and yields, and generates labels and PDF reports.

It's built for chemistry labs that want:

- **No cloud lock-in** — your data lives on your machine, encrypted
  at rest if you choose. No vendor can revoke your access.
- **Audit-ready by design** — every action is logged; the audit
  trail is append-only and exportable as CSV/PDF.
- **Real chemistry workflow** — reactions with stoichiometric
  templates, runs with real-weight tracking and yield calculation,
  mixtures (eluents, buffers, solutions) as first-class entities,
  Avery and thermal labels with GHS pictograms and QR codes.
- **Multilingual** — full Italian and English UI.

Stoic is in **active development** (v0.9.0 → v1.0.0 in progress).
Use in production at your own risk; keep backups.

## Quick start (macOS / Linux)

```bash
# Clone or download
git clone https://github.com/the-stoic-authors/stoic.git
cd stoic-eln

# Set up the virtual environment
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .

# Initialize the database and create the first admin user
export FLASK_APP=stoic_eln
flask init-db
flask create-user --admin

# Run
flask run
# → open http://localhost:5000 in your browser
```

For deployment with systemd, Raspberry Pi, encryption setup, and
automatic backups, see the [Administrator manual](docs/en/admin-manual.md)
(also in [Italian](docs/it/manuale-amministratore.md)).

## Documentation

Stoic ships with three manuals, available both in this repository
and inside the app at `/docs/` once logged in:

- **[User manual](docs/en/user-manual.md)** — lab workflow:
  substances, reactions, runs, mixtures, labels, attachments
- **[Administrator manual](docs/en/admin-manual.md)** —
  installation, user management, encryption, backups, deployment
- **[Developer manual](docs/en/developer-manual.md)** —
  architecture, models, blueprints, testing, internationalization

Italian versions: [Manuale utente](docs/it/manuale-utente.md),
[Manuale amministratore](docs/it/manuale-amministratore.md),
[Manuale sviluppatore](docs/it/manuale-sviluppatore.md).

## Screenshots

*(coming soon — dashboard, reaction template, run execution, label
preview)*

## Features

**Substances** · PubChem import (CAS, SMILES, name) · GHS pictograms
+ H/P phrases · physical properties (MW, density, state) · low-stock
thresholds · deduplication by InChIKey

**Inventory** · per-lot tracking with expiry, supplier, cost ·
Avery L7160/L7164 PDF labels and Brother QL/Dymo thermal labels ·
QR code linking back to the batch URL · per-lot SDS PDF generation

**Reactions** · stoichiometric templates with starting materials,
reagents, products, solvents, catalysts · versioning (draft →
publish, archive of previous versions) · embedded procedures with
steps, temperature, time, workup, checklists

**Runs** · scale the template to your actual mmol, pick lots from
inventory, log real weights, automatic yield computation, automatic
new batch creation for the product · per-run PDF reports

**Mixtures** · first-class entities for solutions, eluents, buffers
· prepare from precursor lots with auto-scaling · same labels and
batch tracking as substances · structured components or quick
labels

**Orders** · plan / order / receive workflow · auto-suggested
shopping list from low-stock alerts · per-order cost tracking ·
auto-creation of inventory lot on receipt

**Backups & encryption** · nightly automatic backups · AES-256-GCM
encrypted backups with Argon2id KDF · live database encryption with
SQLCipher (AES-256-CBC + HMAC-SHA512) · four passphrase modes
(none / prompt-on-boot / file / env var) for different threat
models

**Audit log** · every action tracked with user, timestamp, entity,
details · admin-only full log · CSV and PDF export · append-only

**Internationalization** · full Italian and English UI, runtime
language switching per user

## Stack

Python 3.12+ · Flask 3.x · SQLAlchemy 2.x · SQLite (with optional
SQLCipher) · Jinja2 + HTMX · Bootstrap 5.3 · RDKit · ReportLab ·
cryptography · APScheduler · pytest

## Testing

```bash
.venv/bin/pytest tests/ -q
```

Stoic ships with ~420 tests. Current state at v0.9.0: 414 passing,
6 known legacy failures in `test_reactions.py` (pre-existing, not
blocking; tracked for fix before v1.0).

## License

Stoic is licensed under the **GNU Affero General Public License
v3 or later** (AGPL-3.0-or-later). See [LICENSE](LICENSE) for the
full text.

### What this means for you

- **You can use Stoic for free**, in any setting (academic,
  commercial, personal), with no restrictions.
- **You can modify Stoic** and run your modified version locally
  without sharing your changes.
- **If you distribute** a modified version (a tarball, a Docker
  image, a fork on GitHub) you must publish the source code of
  your modifications under the same AGPLv3 license.
- **If you run Stoic as a network service** that other people use
  (a SaaS, an internal company portal accessible to multiple
  users) you must publish the source code of your modifications
  under the same AGPLv3 license — including any modifications
  made server-side that those users interact with.

In short: you can use it, change it, build on it. But the project
stays open and free for everyone.

### Why AGPLv3

We chose AGPLv3 because Stoic is a web application. A weaker
copyleft license like GPLv3 would let companies modify Stoic, run
it as a SaaS, and not share the improvements. AGPLv3 closes that
loophole — improvements stay public.

### Commercial licensing

If AGPLv3 doesn't fit your use case (e.g. you want to embed Stoic
in a proprietary product without releasing your source), commercial
licenses may be available. See [CONTRIBUTING.md](CONTRIBUTING.md)
for details, or email **the-stoic-authors@proton.me**.

## Contact

- **General questions / bug reports**: open an issue at
  <https://github.com/the-stoic-authors/stoic/issues>.
- **Security disclosures**: email **the-stoic-authors@proton.me**
  privately (please do not open a public issue for security
  vulnerabilities).
- **Commercial licensing**: email **the-stoic-authors@proton.me**.

## Contributing

Contributions are welcome — bug reports, feature requests, code,
docs, translations. See [CONTRIBUTING.md](CONTRIBUTING.md) for the
contribution workflow and the [Contributor License Agreement
(CLA)](CLA.md).

By submitting code or content, you agree to the CLA. The CLA
exists to keep Stoic's licensing options open — including possible
future relicensing for commercial customers — while ensuring your
contribution is always available under AGPLv3 to everyone else.

## Project status

| | |
|---|---|
| Version | 0.9.0 (preparing 1.0) |
| First public release | 2026 |
| Tests | 414 / 420 passing |
| Languages | Italian, English |
| Platforms tested | macOS (Intel, Apple Silicon), Linux x86_64 |
| Platforms planned | Raspberry Pi (ARM64) |
| Platforms not supported | Windows (use WSL2) |

## Acknowledgments

Stoic was built by a chemist for chemists. It draws inspiration
from [eLabFTW](https://www.elabftw.net/) (AGPLv3 ELN with a similar
philosophy) and from years of frustration with proprietary lab
software that gates access to your own data behind annual
subscriptions.

Built with [Flask](https://flask.palletsprojects.com/),
[SQLAlchemy](https://www.sqlalchemy.org/),
[RDKit](https://www.rdkit.org/),
[Bootstrap](https://getbootstrap.com/),
[HTMX](https://htmx.org/), and many other open-source libraries —
each one published under licenses that made building Stoic
possible. We try to repay the debt by keeping Stoic open.

---

<div align="center">

**Stoic** · Copyright © 2026 The Stoic Authors · AGPLv3

</div>
