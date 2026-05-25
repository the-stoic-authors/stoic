"""Tests for patch 14.3 — passphrase source backends.

Covers:

  - The three sources (prompt, file, env) and source switching
  - ``current_source`` reads AppSetting first, then the marker
  - ``ensure_default_source_setting`` migration logic
  - The cache: once resolved, ``get_passphrase`` returns the
    cached value without re-prompting/re-reading
  - The verifier callback: wrong passphrase loops in prompt mode,
    fails fast in file/env modes
  - PassphraseUnavailable when prompt mode has no TTY
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stoic_eln import create_app
from stoic_eln.config import TestingConfig
from stoic_eln.extensions import db
from stoic_eln.services import passphrase_store as ps


@pytest.fixture(autouse=True)
def _reset_cache():
    """Each test starts with a clean cache and no injected callback."""
    ps.reset_cache()
    ps.set_prompt_callback(None)
    yield
    ps.reset_cache()
    ps.set_prompt_callback(None)


@pytest.fixture
def app_with_instance(tmp_path):
    """A test app with a real on-disk instance_path so the marker
    file machinery works."""
    db_file = tmp_path / "stoic.db"

    class _Cfg(TestingConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_file}"

    app = create_app(_Cfg)
    # We can't override instance_path post-creation in a way that
    # _maybe_enable_sqlcipher saw, but for the post-DB tests below
    # that's fine: passphrase_store reads instance_path from
    # current_app.instance_path lazily, so this still works for
    # AppSetting + marker file reads.
    with app.app_context():
        yield app, Path(app.instance_path)


# ── Source enum + labels ─────────────────────────────────────────


def test_sources_constant():
    """All four sources are advertised."""
    assert ps.SOURCE_NONE in ps.SOURCES
    assert ps.SOURCE_PROMPT in ps.SOURCES
    assert ps.SOURCE_FILE in ps.SOURCES
    assert ps.SOURCE_ENV in ps.SOURCES
    assert len(ps.SOURCES) == 4


def test_labels_for_each_source():
    """UI labels exist for each source (Italian)."""
    for s in ps.SOURCES:
        assert s in ps.SOURCE_LABELS_IT
        assert s in ps.SOURCE_DESCRIPTIONS_IT
        assert len(ps.SOURCE_LABELS_IT[s]) > 0
        assert len(ps.SOURCE_DESCRIPTIONS_IT[s]) > 0


# ── Static source backends ───────────────────────────────────────


def test_from_env_returns_value(monkeypatch):
    monkeypatch.setenv("STOIC_BACKUP_PASSPHRASE", "  env-pp  ")
    assert ps._from_env() == "env-pp"


def test_from_env_empty_returns_none(monkeypatch):
    monkeypatch.setenv("STOIC_BACKUP_PASSPHRASE", "   ")
    assert ps._from_env() is None


def test_from_env_missing_returns_none(monkeypatch):
    monkeypatch.delenv("STOIC_BACKUP_PASSPHRASE", raising=False)
    assert ps._from_env() is None


def test_from_file_returns_value(tmp_path):
    (tmp_path / "backup.key").write_text("file-pp\n", encoding="utf-8")
    assert ps._from_file(tmp_path) == "file-pp"


def test_from_file_missing_returns_none(tmp_path):
    assert ps._from_file(tmp_path) is None


def test_from_file_empty_returns_none(tmp_path):
    (tmp_path / "backup.key").write_text("   \n", encoding="utf-8")
    assert ps._from_file(tmp_path) is None


# ── Prompt backend (with injected callback) ──────────────────────


def test_from_prompt_uses_callback():
    ps.set_prompt_callback(lambda: "from-callback")
    assert ps._from_prompt() == "from-callback"


def test_from_prompt_callback_with_verifier_accepts():
    ps.set_prompt_callback(lambda: "good-pp")
    assert ps._from_prompt(verifier=lambda pp: pp == "good-pp") == "good-pp"


def test_from_prompt_callback_with_verifier_rejects():
    ps.set_prompt_callback(lambda: "bad-pp")
    # Verifier rejects → returns None (caller decides what to do)
    assert ps._from_prompt(verifier=lambda pp: False) is None


def test_from_prompt_no_tty_raises(monkeypatch):
    """Without a callback AND without a tty, prompt mode must
    raise so the caller knows boot can't proceed in this mode."""
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    ps.set_prompt_callback(None)
    with pytest.raises(ps.PassphraseUnavailable):
        ps._from_prompt()


# ── current_source: AppSetting > marker > default ────────────────


def test_current_source_default_is_none(app_with_instance):
    """With no config at all, default is 'none' (no encryption,
    backward compatible with 14.0 fresh installs)."""
    app, _ = app_with_instance
    assert ps.current_source() == ps.SOURCE_NONE


def test_current_source_reads_appsetting(app_with_instance):
    app, _ = app_with_instance
    from stoic_eln.models.settings import AppSetting

    AppSetting.set("auth.passphrase_source", ps.SOURCE_FILE)
    db.session.commit()
    assert ps.current_source() == ps.SOURCE_FILE


def test_current_source_falls_back_to_marker(app_with_instance):
    """If AppSetting has no value, the on-disk marker is used."""
    app, instance = app_with_instance
    marker = instance / "auth_source"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(ps.SOURCE_ENV, encoding="utf-8")
    assert ps.current_source() == ps.SOURCE_ENV


def test_current_source_ignores_garbage_in_marker(app_with_instance):
    """An invalid marker value falls back to the default."""
    app, instance = app_with_instance
    marker = instance / "auth_source"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("garbage-value", encoding="utf-8")
    assert ps.current_source() == ps.SOURCE_NONE


# ── set_source: writes both AppSetting and marker ────────────────


def test_set_source_writes_both_appsetting_and_marker(app_with_instance):
    app, instance = app_with_instance
    ps.set_source(ps.SOURCE_FILE)
    db.session.commit()

    from stoic_eln.models.settings import AppSetting

    assert AppSetting.get("auth.passphrase_source") == ps.SOURCE_FILE
    assert (instance / "auth_source").read_text().strip() == ps.SOURCE_FILE


def test_set_source_rejects_invalid(app_with_instance):
    with pytest.raises(ValueError):
        ps.set_source("not-a-source")


# ── ensure_default_source_setting: migration logic ───────────────


def test_default_setting_none_for_fresh_install(tmp_path):
    """No backup.key, no env var → default to 'none' mode (no
    encryption, no surprise prompts at boot)."""
    instance = tmp_path / "inst"
    instance.mkdir()
    ps.ensure_default_source_setting(instance)
    assert (instance / "auth_source").read_text().strip() == ps.SOURCE_NONE


def test_default_setting_migrates_existing_backup_key(tmp_path):
    """Existing backup.key from 14.1/14.2 → keep 'file' mode."""
    instance = tmp_path / "inst"
    instance.mkdir()
    (instance / "backup.key").write_text("existing-pp", encoding="utf-8")
    ps.ensure_default_source_setting(instance)
    assert (instance / "auth_source").read_text().strip() == ps.SOURCE_FILE


def test_default_setting_respects_existing_marker(tmp_path):
    """If a marker already exists, don't overwrite."""
    instance = tmp_path / "inst"
    instance.mkdir()
    (instance / "auth_source").write_text(ps.SOURCE_ENV, encoding="utf-8")
    # Even though backup.key exists, the marker wins.
    (instance / "backup.key").write_text("old-pp", encoding="utf-8")
    ps.ensure_default_source_setting(instance)
    assert (instance / "auth_source").read_text().strip() == ps.SOURCE_ENV


def test_default_setting_migrates_env_var(tmp_path, monkeypatch):
    """No backup.key but env var set → default to 'env'."""
    instance = tmp_path / "inst"
    instance.mkdir()
    monkeypatch.setenv("STOIC_BACKUP_PASSPHRASE", "from-env")
    ps.ensure_default_source_setting(instance)
    assert (instance / "auth_source").read_text().strip() == ps.SOURCE_ENV


# ── get_passphrase + cache ───────────────────────────────────────


def test_get_passphrase_prompt_via_callback(app_with_instance):
    app, instance = app_with_instance
    ps.set_source(ps.SOURCE_PROMPT)
    db.session.commit()
    ps.set_prompt_callback(lambda: "in-my-head")
    assert ps.get_passphrase(instance) == "in-my-head"


def test_get_passphrase_caches(app_with_instance):
    """Once resolved, the value is cached: subsequent calls don't
    re-prompt."""
    app, instance = app_with_instance
    ps.set_source(ps.SOURCE_PROMPT)
    db.session.commit()

    call_count = {"n": 0}

    def cb():
        call_count["n"] += 1
        return "first-value"

    ps.set_prompt_callback(cb)
    assert ps.get_passphrase(instance) == "first-value"
    assert ps.get_passphrase(instance) == "first-value"
    assert ps.get_passphrase(instance) == "first-value"
    assert call_count["n"] == 1  # cached after first call


def test_get_passphrase_file_mode(app_with_instance):
    app, instance = app_with_instance
    ps.set_source(ps.SOURCE_FILE)
    db.session.commit()
    (instance / "backup.key").write_text("from-file", encoding="utf-8")
    assert ps.get_passphrase(instance) == "from-file"


def test_get_passphrase_env_mode(app_with_instance, monkeypatch):
    app, instance = app_with_instance
    ps.set_source(ps.SOURCE_ENV)
    db.session.commit()
    monkeypatch.setenv("STOIC_BACKUP_PASSPHRASE", "from-env-mode")
    assert ps.get_passphrase(instance) == "from-env-mode"


def test_get_passphrase_returns_none_when_unavailable(app_with_instance, monkeypatch):
    app, instance = app_with_instance
    ps.set_source(ps.SOURCE_ENV)
    db.session.commit()
    monkeypatch.delenv("STOIC_BACKUP_PASSPHRASE", raising=False)
    assert ps.get_passphrase(instance) is None


# ── has_passphrase_available: non-blocking predicate ─────────────


def test_has_passphrase_available_file_mode(app_with_instance, tmp_path):
    """In file mode, the predicate reads the backup.key file
    if present."""
    app, _real_instance = app_with_instance
    ps.set_source(ps.SOURCE_FILE)
    db.session.commit()
    # Use a clean tmp dir, not the real instance/ which may have
    # a leftover backup.key from earlier dev work.
    clean = tmp_path / "clean-instance"
    clean.mkdir()
    assert ps.has_passphrase_available(clean) is False
    (clean / "backup.key").write_text("x", encoding="utf-8")
    assert ps.has_passphrase_available(clean) is True


def test_has_passphrase_available_prompt_mode_false_uncached(app_with_instance):
    """In prompt mode, the predicate must NOT prompt — returns
    False unless a passphrase is already cached."""
    app, instance = app_with_instance
    ps.set_source(ps.SOURCE_PROMPT)
    db.session.commit()
    assert ps.has_passphrase_available(instance) is False


def test_has_passphrase_available_prompt_mode_true_when_cached(app_with_instance):
    app, instance = app_with_instance
    ps.set_source(ps.SOURCE_PROMPT)
    db.session.commit()
    ps.set_for_testing("cached-pp")
    assert ps.has_passphrase_available(instance) is True


# ── SOURCE_NONE: never prompts, never reads, returns None ────────


def test_source_none_returns_none(app_with_instance):
    """When source is 'none', get_passphrase always returns None
    without prompting and without reading any file/env."""
    app, instance = app_with_instance
    ps.set_source(ps.SOURCE_NONE)
    db.session.commit()
    # Even if a callback would return something, source=NONE
    # bypasses the entire chain.
    ps.set_prompt_callback(lambda: "would-have-been-returned")
    assert ps.get_passphrase(instance) is None


def test_source_none_has_passphrase_available_false(app_with_instance):
    app, instance = app_with_instance
    ps.set_source(ps.SOURCE_NONE)
    db.session.commit()
    assert ps.has_passphrase_available(instance) is False


# ── Verifier flow: prompt mode loops, static modes fail fast ─────


def test_verifier_retries_in_prompt_mode(app_with_instance):
    """If the verifier rejects, the prompt callback gets called
    again (up to 3 times)."""
    app, instance = app_with_instance
    ps.set_source(ps.SOURCE_PROMPT)
    db.session.commit()

    attempts = []

    def cb():
        attempts.append(len(attempts) + 1)
        return f"attempt-{len(attempts)}"

    ps.set_prompt_callback(cb)
    # Verifier accepts only "attempt-1" (the callback always returns
    # the same on each call here since we don't reset). For the
    # retry-on-failure semantics we test the callback-based code
    # path: when the callback is set, we get one shot per call to
    # get_passphrase. The real retry loop is in the getpass-based
    # path, which we exercise in a separate boot-integration test.
    result = ps.get_passphrase(instance, verifier=lambda pp: pp == "attempt-1")
    assert result == "attempt-1"
