# Contributing to Stoic

Thanks for considering a contribution to Stoic. This document
covers how to report issues, propose changes, and submit code.

By contributing to this project you agree to the
**[Contributor License Agreement (CLA)](CLA.md)** — see the
[CLA section](#contributor-license-agreement) below for the short
version.

## Table of contents

- [Reporting bugs](#reporting-bugs)
- [Proposing features](#proposing-features)
- [Pull requests](#pull-requests)
- [Code style](#code-style)
- [Translations](#translations)
- [Tests](#tests)
- [Documentation](#documentation)
- [Contributor License Agreement](#contributor-license-agreement)
- [Code of conduct](#code-of-conduct)
- [Commercial licensing inquiries](#commercial-licensing-inquiries)

## Reporting bugs

If you found a bug, please open an issue. A good bug report
includes:

1. **What you did** — minimum steps to reproduce
2. **What you expected** — the behavior you were aiming for
3. **What actually happened** — including any error message or
   stack trace
4. **Your environment** — Stoic version (`git log -1`), Python
   version (`python --version`), OS, browser
5. **Screenshot** if it's a UI bug

Please don't report **security issues** in public issues. See
[Security](#security) below.

### Security

If you find a security vulnerability (data leak, authentication
bypass, encryption flaw, injection vector), do **not** open a
public issue. Email **the-stoic-authors@proton.me**, with subject
line starting with `[SECURITY]`. We'll respond within 7 days and
coordinate a fix and disclosure timeline.

## Proposing features

Open an issue describing:

- The problem you're trying to solve (lab workflow, not the
  technical solution)
- One or two examples of how it would work
- Why you can't solve it with the current features

For larger features, please discuss in an issue **before** writing
code. We may suggest a different approach, or the feature may be
out of scope. Saves everyone's time.

Features that are **out of scope** for Stoic:

- FDA 21 CFR Part 11 electronic signatures (use a regulated ELN)
- ChemDraw integration (too expensive to license)
- Mobile native apps (the web UI is mobile-responsive)
- Cloud SaaS multi-tenancy (Stoic is single-tenant by design)

## Pull requests

1. **Fork** the repository on GitHub.
2. **Branch** from `main`: `git checkout -b fix-some-bug` or
   `feature/add-some-thing`.
3. **Make focused changes.** One PR = one logical change.
   Mega-PRs that touch 50 files are very hard to review.
4. **Add tests** for new code or for the bug you're fixing. See
   [Tests](#tests) below.
5. **Update documentation** if you change user-facing behavior.
   See [Documentation](#documentation).
6. **Update translations** if you added or changed user-facing
   strings. See [Translations](#translations).
7. **Run the test suite locally**: `pytest tests/ -q`. Make sure
   you don't introduce regressions.
8. **Open the PR** against `main` with a clear description: what
   problem it solves, what approach you took, how to test it
   manually.

### What we look for in PR review

- **Tests pass** (the CI will run them)
- **No regressions** in unrelated areas
- **Code style consistent** with the rest of the codebase
- **Documentation updated** if behavior changes
- **Translations updated** if user-facing text changes
- **Commit messages are descriptive** (not "fix" or "wip")
- **CLA accepted** — implicit when you submit the PR

We may suggest changes during review. That's normal. The goal is
to keep Stoic high quality and maintainable long-term.

## Code style

Stoic uses Python 3.12+ with type hints. Conventions:

- `from __future__ import annotations` at the top of every Python
  file
- Type hints on public function signatures
- Docstrings for non-trivial functions (English, even though
  user-facing UI is in Italian source language)
- Lines preferably under 88 characters, hard limit at 100
- No `f"..."` inside `_(...)` or `_l(...)` — Babel can't extract
  f-strings; use `%`-format
- Wrap all user-visible strings in `_("...")` (Jinja templates) or
  `_l("...")` (form classes, service-layer strings)

Tooling:

```bash
# Format and lint
.venv/bin/ruff format stoic_eln/ tests/
.venv/bin/ruff check stoic_eln/ tests/

# Type check (best-effort, not strict)
.venv/bin/mypy stoic_eln/
```

No pre-commit hook is required — we run these manually before
committing. CI will flag style violations.

## Translations

Stoic is **Italian-sourced, English-target**. Italian is the
canonical language: all `_("...")` and `_l("...")` calls use the
Italian string as the source.

If you add a new user-facing string:

```bash
# Extract strings from templates and Python files
pybabel extract -F babel.cfg -o messages.pot .

# Update the .po catalogs
pybabel update -i messages.pot -d stoic_eln/translations

# Heal: make Italian msgstr = msgid (Italian is canonical)
python scripts/heal_it_translations.py

# Healing English: apply the EN_FIXES dict for new strings
python scripts/heal_en_translations.py
# (script will report "still empty: N" — add those to EN_FIXES)

# Force-override: apply curated translations from OVERRIDES dict
python scripts/override_en_translations.py

# Compile .mo for runtime
pybabel compile -d stoic_eln/translations
```

The `OVERRIDES` dict in `scripts/override_en_translations.py` is
the **source of truth** for English translations. Don't edit the
`.po` files by hand — your changes will be overwritten on the
next override run.

To add a new language (say French), the procedure exists but is
not yet automated; open an issue and we'll guide you through it.

## Tests

Stoic uses pytest. The test suite lives in `tests/`.

```bash
.venv/bin/pytest tests/                  # all tests
.venv/bin/pytest tests/test_foo.py       # one file
.venv/bin/pytest tests/ -k "foo"         # tests matching a name
.venv/bin/pytest tests/ -v               # verbose
.venv/bin/pytest tests/ -x               # stop on first failure
```

**When you add a feature:** add tests in `tests/test_<feature>.py`.
At minimum: a smoke test for each new route, and a test for each
new computation/service.

**When you fix a bug:** add a regression test that fails before
your fix and passes after. This is the single most useful thing
you can do to prevent the bug from coming back.

Tests use `SQLite :memory:` by default and complete in ~2 minutes.
If you write a test that's slow (>10 seconds), mark it `@pytest.mark.slow`
so we can skip it in the default run.

The `tests/conftest.py` fixture file provides:

- `app` — a fresh `Flask` app with `TestingConfig` per test
- `client` — Flask test client
- `admin_user` — pre-created admin user

## Documentation

If your change is **user-visible**, update:

- `docs/it/manuale-utente.md` and `docs/en/user-manual.md` (lab
  workflow features)
- `docs/it/manuale-amministratore.md` and
  `docs/en/admin-manual.md` (configuration, deployment, security)
- `docs/it/manuale-sviluppatore.md` and
  `docs/en/developer-manual.md` (architecture, code structure)

If your change is significant, add an entry to `CHANGELOG.md`
under "Unreleased".

## Contributor License Agreement

By submitting a contribution to this project (code, documentation,
translations, anything), you agree to the **Contributor License
Agreement** in [CLA.md](CLA.md).

### What the CLA says, in plain English

1. **You own what you contribute.** You keep the copyright to your
   code. You're not transferring ownership.

2. **You grant the project a license to use it under AGPLv3.**
   Anyone using Stoic gets your contribution under AGPLv3, same
   as the rest of the codebase.

3. **You also grant the maintainer the right to relicense** your
   contribution under other terms — including a possible
   commercial license sold to customers who need a non-AGPLv3
   version. This is the **dual licensing option** that keeps
   Stoic financially sustainable in the long term.

4. **You confirm you have the right to contribute** — i.e. you
   wrote the code yourself, or it's already compatible-licensed
   and properly attributed, or your employer (if any) has
   authorized you to contribute.

5. **No warranties.** You're contributing "as is", with no
   guarantees of fitness.

That's it. It's a one-time agreement, valid for all your
contributions to this project. By opening a PR, you're agreeing
to it. No paperwork to sign.

If you can't or don't want to accept the CLA — for example,
because your employer doesn't allow it, or because you object to
the dual-licensing clause — please open an issue describing your
contribution instead, and we can discuss alternatives.

## Code of conduct

Be kind. Assume good faith. Disagree about technical decisions,
not about people. If someone reports harassment or abuse, we'll
investigate and take action.

Specifically:

- Personal attacks are not okay
- Discrimination based on race, gender, sexual orientation,
  religion, nationality, ability, or any other protected
  characteristic is not okay
- Sexual content or harassment is not okay
- Doxxing or threats are not okay

If you experience or witness behavior that violates this, email **the-stoic-authors@proton.me**.

## Commercial licensing inquiries

Stoic is AGPLv3 by default. If you need a different license — for
example, you want to embed Stoic into a proprietary product, or
your company's lawyers won't accept AGPLv3 for internal use —
commercial licenses may be available.

Inquiries: open a GitHub issue tagged `licensing-question` with a
brief description of your use case, or email
**the-stoic-authors@proton.me** privately.

---

Thanks again for contributing.
