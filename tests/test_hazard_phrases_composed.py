"""Tests for patch 13.7: H/P phrase resolution including composed codes
(P301+P330+P331 etc.) and pubchem extraction of those codes."""

from __future__ import annotations


from stoic_eln.extensions import db
from stoic_eln.models import HazardPhrase
from stoic_eln.services.hazard_phrases import parse_codes, resolve_phrases


def _seed_phrases(app):
    """Drop a few canonical CLP phrases used by the tests."""
    with app.app_context():
        db.session.add_all([
            HazardPhrase(code="H225", category="H",
                         text_en="Highly flammable liquid and vapour.",
                         text_it="Liquido e vapori facilmente infiammabili."),
            HazardPhrase(code="H319", category="H",
                         text_en="Causes serious eye irritation.",
                         text_it="Provoca grave irritazione oculare."),
            HazardPhrase(code="P210", category="P",
                         text_en="Keep away from heat.",
                         text_it="Tenere lontano da fonti di calore."),
            HazardPhrase(code="P301", category="P",
                         text_en="IF SWALLOWED:",
                         text_it="IN CASO DI INGESTIONE:"),
            HazardPhrase(code="P330", category="P",
                         text_en="Rinse mouth.",
                         text_it="Sciacquare la bocca."),
            HazardPhrase(code="P331", category="P",
                         text_en="Do NOT induce vomiting.",
                         text_it="NON provocare il vomito."),
            HazardPhrase(code="P302", category="P",
                         text_en="IF ON SKIN:",
                         text_it="IN CASO DI CONTATTO CON LA PELLE:"),
            HazardPhrase(code="P361", category="P",
                         text_en="Take off immediately all contaminated clothing.",
                         text_it="Togliere immediatamente tutti gli indumenti contaminati."),
            HazardPhrase(code="P354", category="P",
                         text_en="Immediately rinse with water for several minutes.",
                         text_it="Sciacquare immediatamente con acqua per diversi minuti."),
        ])
        db.session.commit()


def test_parse_codes_preserves_plus_signs(app):
    """parse_codes splits on comma; internal + stays part of the code."""
    codes = parse_codes("H225, P301+P330+P331, P210")
    assert codes == ["H225", "P301+P330+P331", "P210"]


def test_parse_codes_uppercases_and_strips(app):
    codes = parse_codes("  h225 ,  p301+p330+p331  ,  ")
    assert codes == ["H225", "P301+P330+P331"]


def test_parse_codes_empty(app):
    assert parse_codes("") == []
    assert parse_codes(None) == []  # type: ignore[arg-type]


def test_resolve_atomic_phrase(app):
    """Plain H225 → its text in the requested locale."""
    _seed_phrases(app)
    with app.app_context():
        out = resolve_phrases(["H225"], "en")
    assert len(out) == 1
    assert out[0]["code"] == "H225"
    assert "flammable" in out[0]["text"].lower()


def test_resolve_composed_phrase_english(app):
    """P301+P330+P331 → joined English text."""
    _seed_phrases(app)
    with app.app_context():
        out = resolve_phrases(["P301+P330+P331"], "en")
    assert len(out) == 1
    assert out[0]["code"] == "P301+P330+P331"
    text = out[0]["text"]
    assert "IF SWALLOWED:" in text
    assert "Rinse mouth." in text
    assert "Do NOT induce vomiting." in text
    # Order is preserved
    assert text.index("IF SWALLOWED:") < text.index("Rinse mouth.")
    assert text.index("Rinse mouth.") < text.index("Do NOT induce vomiting.")


def test_resolve_composed_phrase_italian(app):
    """The same composed code resolves to italian when locale='it'."""
    _seed_phrases(app)
    with app.app_context():
        out = resolve_phrases(["P301+P330+P331"], "it")
    text = out[0]["text"]
    assert "INGESTIONE" in text
    assert "Sciacquare la bocca" in text
    assert "NON provocare il vomito" in text


def test_resolve_mixed_atomic_and_composed(app):
    """A list with both kinds → each rendered correctly, order preserved."""
    _seed_phrases(app)
    with app.app_context():
        out = resolve_phrases(
            ["H225", "P301+P330+P331", "P302+P361+P354", "P210"],
            "en",
        )
    assert [r["code"] for r in out] == [
        "H225", "P301+P330+P331", "P302+P361+P354", "P210",
    ]
    assert "flammable" in out[0]["text"].lower()
    assert "IF SWALLOWED:" in out[1]["text"]
    assert "IF ON SKIN:" in out[2]["text"]
    assert "Keep away from heat" in out[3]["text"]


def test_resolve_unknown_code_returns_empty_text(app):
    """A code not in the DB returns an entry with empty text."""
    _seed_phrases(app)
    with app.app_context():
        out = resolve_phrases(["H999"], "en")
    assert out == [{"code": "H999", "text": ""}]


def test_resolve_partial_composed_code(app):
    """If some segments of a composed code aren't in the DB, we
    still get the parts that ARE present, joined."""
    _seed_phrases(app)
    with app.app_context():
        # P999 isn't seeded; P301 and P330 are
        out = resolve_phrases(["P301+P999+P330"], "en")
    assert len(out) == 1
    text = out[0]["text"]
    assert "IF SWALLOWED:" in text
    assert "Rinse mouth." in text
    # No leading/trailing weird whitespace from the missing P999
    assert text == "IF SWALLOWED: Rinse mouth."


def test_resolve_empty_list(app):
    """Empty input → empty output, no DB hit needed."""
    with app.app_context():
        assert resolve_phrases([], "en") == []


def test_pubchem_regex_captures_composed_codes():
    """The regex in pubchem._fill_ghs must capture P301+P330+P331
    as a single token, not three. Direct regex test."""
    import re
    pat = (
        r"\b("
        r"(?:H\d{3}|EUH\d{3}|P\d{3})"
        r"(?:\+(?:H\d{3}|EUH\d{3}|P\d{3}))*"
        r")\b"
    )
    sample = (
        "P301+P330+P331: IF SWALLOWED: Rinse mouth. "
        "Do NOT induce vomiting. P210 Keep away from heat. "
        "P302+P361+P354 IF ON SKIN: ..."
    )
    matches = [m.group(1) for m in re.finditer(pat, sample)]
    assert "P301+P330+P331" in matches
    assert "P302+P361+P354" in matches
    assert "P210" in matches
    # No segment leaked as a standalone code
    assert "P301" not in matches
    assert "P330" not in matches
    assert "P331" not in matches
