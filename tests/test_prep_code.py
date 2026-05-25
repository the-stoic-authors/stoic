"""Tests for the mixture preparation code service (patch 13.2)."""

from __future__ import annotations

import pytest

from stoic_eln.services import prep_code
from datetime import UTC


def test_slugify_basic_names(app):
    assert prep_code.slugify_mixture_name("HCl 6N") == "HCL6N"
    assert prep_code.slugify_mixture_name("HCl 1N") == "HCL1N"
    assert prep_code.slugify_mixture_name("Eluente A 95:5") == "ELUENTEA955"
    assert prep_code.slugify_mixture_name("Buffer pH 7.4") == "BUFFERPH74"


def test_slugify_truncates_long_names(app):
    name = "Very Long Mixture Name That Exceeds The Limit"
    slug = prep_code.slugify_mixture_name(name)
    assert len(slug) <= prep_code.SLUG_MAX_LEN
    assert slug == "VERYLONGMIXTUREN"


def test_slugify_empty_falls_back(app):
    assert prep_code.slugify_mixture_name("") == "MIX"
    assert prep_code.slugify_mixture_name("   ") == "MIX"
    assert prep_code.slugify_mixture_name("!!!") == "MIX"


def test_format_prep_code_default(app):
    code = prep_code.format_prep_code(
        fmt="{mix}-{year}-{seq:03d}",
        mix="HCL6N",
        year=2026,
        seq=1,
    )
    assert code == "HCL6N-2026-001"


def test_validate_format_rejects_unknown_placeholders(app):
    with pytest.raises(ValueError, match="Placeholder"):
        prep_code.validate_format("{op}-{mix}-{seq}")  # 'op' is not allowed


def test_validate_format_requires_seq(app):
    with pytest.raises(ValueError, match="seq"):
        prep_code.validate_format("{mix}-{year}")


def test_validate_format_balanced_braces(app):
    with pytest.raises(ValueError, match="graffe"):
        prep_code.validate_format("{mix-{year}-{seq}")


def test_generate_prep_code_increments_sequence(app):
    """Two prep codes for the same mixture in the same year get
    sequential seq numbers."""
    from datetime import datetime
    from stoic_eln.extensions import db
    from stoic_eln.models import Group, Mixture
    from stoic_eln.models.mixture_prep import MixturePrep

    with app.app_context():
        g = Group(name="L", slug="l")
        db.session.add(g)
        db.session.flush()
        m = Mixture(
            name="HCl 6N",
            kind="solution",
            primary_concentration=6.0,
            primary_concentration_unit="N",
        )
        db.session.add(m)
        db.session.flush()

        code1, seq1 = prep_code.generate_prep_code(
            mixture_name=m.name,
            mixture_id=m.id,
            year=2026,
        )
        # Persist a fake prep so the next call sees a non-empty history.
        db.session.add(
            MixturePrep(
                code=code1,
                sequence=seq1,
                year=2026,
                mixture_id=m.id,
                target_quantity=1.0,
                target_quantity_unit="L",
                prepared_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        db.session.commit()
        code2, seq2 = prep_code.generate_prep_code(
            mixture_name=m.name,
            mixture_id=m.id,
            year=2026,
        )
    assert seq1 == 1
    assert seq2 == 2
    assert code1.endswith("-001")
    assert code2.endswith("-002")


def test_scope_mix_isolates_sequences_per_mixture(app):
    """Under ``mix`` scope, two different mixtures have independent
    sequence counters."""
    from datetime import datetime
    from stoic_eln.extensions import db
    from stoic_eln.models import Group, Mixture
    from stoic_eln.models.mixture_prep import MixturePrep

    with app.app_context():
        prep_code.set_scope("mix")
        g = Group(name="L2", slug="l2")
        db.session.add(g)
        db.session.flush()
        m_a = Mixture(
            name="HCl 1N",
            kind="solution",
            primary_concentration=1.0,
            primary_concentration_unit="N",
        )
        m_b = Mixture(
            name="HCl 6N",
            kind="solution",
            primary_concentration=6.0,
            primary_concentration_unit="N",
        )
        db.session.add_all([m_a, m_b])
        db.session.flush()

        # Register one prep against m_a, none against m_b yet.
        code_a, seq_a = prep_code.generate_prep_code(
            mixture_name=m_a.name,
            mixture_id=m_a.id,
            year=2026,
        )
        db.session.add(
            MixturePrep(
                code=code_a,
                sequence=seq_a,
                year=2026,
                mixture_id=m_a.id,
                target_quantity=1.0,
                target_quantity_unit="L",
                prepared_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        db.session.commit()

        # Now generate for m_b — under 'mix' scope it should be #1, not #2.
        code_b, seq_b = prep_code.generate_prep_code(
            mixture_name=m_b.name,
            mixture_id=m_b.id,
            year=2026,
        )
        # Reset to default so we don't bleed state into other tests.
        prep_code.set_scope("lab")
    assert seq_a == 1
    assert seq_b == 1
    assert code_a.endswith("-001")
    assert code_b.endswith("-001")
