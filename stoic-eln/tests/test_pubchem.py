"""Tests for PubChem service with HTTP mocking via respx."""

from __future__ import annotations

import json

import pytest
import respx
from httpx import Response

from stoic_eln.services import pubchem


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _props_response(cid=702, **overrides):
    """Build a fake PUG-REST property response."""
    base = {
        "MolecularFormula": "C2H6O",
        "MolecularWeight": "46.07",
        "CanonicalSMILES": "CCO",
        "IsomericSMILES": "CCO",
        "InChI": "InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3",
        "InChIKey": "LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
        "IUPACName": "ethanol",
    }
    base.update(overrides)
    return {"PropertyTable": {"Properties": [{"CID": cid, **base}]}}


def _synonyms_response(synonyms):
    return {"InformationList": {"Information": [{"CID": 702, "Synonym": synonyms}]}}


def _ghs_response_etoh():
    """Minimal PUG-View GHS section for ethanol (Flammable, H225)."""
    return {
        "Record": {
            "Section": [
                {
                    "TOCHeading": "GHS Classification",
                    "Information": [
                        {
                            "Value": {
                                "StringWithMarkup": [
                                    {"String": "GHS02", "Markup": [
                                        {"URL": "https://example.com/pictograms/GHS02.svg",
                                         "Type": "Icon"}
                                    ]}
                                ]
                            }
                        },
                        {
                            "Value": {
                                "StringWithMarkup": [
                                    {"String": "Flame [Warning Flammable liquids - Category 2]"}
                                ]
                            }
                        },
                        {
                            "Value": {
                                "StringWithMarkup": [
                                    {"String": "H225 (Highly flammable liquid and vapour); P210"}
                                ]
                            }
                        },
                    ],
                }
            ]
        }
    }


# ─── Detection ───────────────────────────────────────────────────────────────


def test_detect_query_type_cid():
    assert pubchem._detect_query_type("702") == "cid"


def test_detect_query_type_inchikey():
    assert pubchem._detect_query_type("LFQSCWFLJHTTHZ-UHFFFAOYSA-N") == "inchikey"


def test_detect_query_type_inchi():
    assert pubchem._detect_query_type("InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3") == "inchi"


def test_detect_query_type_cas():
    assert pubchem._detect_query_type("64-17-5") == "cas"


def test_detect_query_type_smiles():
    # SMILES with explicit chemistry chars
    assert pubchem._detect_query_type("CC(=O)O") == "smiles"
    assert pubchem._detect_query_type("c1ccccc1") == "smiles"
    # Plain "CCO" is ambiguous and falls back to "name" — that's expected,
    # users can pick "smiles" explicitly in the form.


def test_detect_query_type_smiles_simple_falls_to_name():
    # No special chars → looks like a name (e.g. could be a synonym match)
    assert pubchem._detect_query_type("CCO") == "name"


def test_detect_query_type_name_default():
    assert pubchem._detect_query_type("ethanol") == "name"


# ─── Search workflow ─────────────────────────────────────────────────────────


@respx.mock
def test_search_by_cas_returns_full_result():
    pubchem.cache_clear()
    respx.get("https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/64-17-5/cids/JSON").mock(
        return_value=Response(200, json={"IdentifierList": {"CID": [702]}})
    )
    respx.get(
        f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/702/property/{pubchem.PROPERTIES}/JSON"
    ).mock(return_value=Response(200, json=_props_response()))
    respx.get("https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/702/synonyms/JSON").mock(
        return_value=Response(200, json=_synonyms_response(["Ethanol", "64-17-5", "ethyl alcohol"]))
    )
    respx.get("https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/702/JSON").mock(
        return_value=Response(200, json=_ghs_response_etoh())
    )

    result = pubchem.search("64-17-5")
    assert result.cid == 702
    assert result.molecular_formula == "C2H6O"
    assert result.molecular_weight == pytest.approx(46.07)
    assert result.smiles == "CCO"
    assert result.inchi_key == "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"
    assert result.cas_number == "64-17-5"
    assert "Ethanol" in (result.name or "")
    assert "GHS02" in result.ghs_pictograms
    assert "H225" in result.h_phrases
    assert "P210" in result.p_phrases


@respx.mock
def test_search_not_found_raises():
    pubchem.cache_clear()
    respx.get("https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/asdfqwerty999/cids/JSON").mock(
        return_value=Response(404)
    )
    with pytest.raises(pubchem.PubChemNotFound):
        pubchem.search("asdfqwerty999", query_type="name")


@respx.mock
def test_search_caches_results():
    pubchem.cache_clear()
    route = respx.get("https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/water/cids/JSON")
    route.mock(return_value=Response(200, json={"IdentifierList": {"CID": [962]}}))
    # Other endpoints return empty data
    respx.get(
        f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/962/property/{pubchem.PROPERTIES}/JSON"
    ).mock(return_value=Response(200, json={"PropertyTable": {"Properties": [{"CID": 962}]}}))
    respx.get("https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/962/synonyms/JSON").mock(
        return_value=Response(200, json=_synonyms_response(["Water"]))
    )
    respx.get("https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/962/JSON").mock(
        return_value=Response(404)
    )

    r1 = pubchem.search("water", query_type="name")
    initial_calls = route.call_count
    r2 = pubchem.search("water", query_type="name")
    # Second call should hit cache (no new HTTP request)
    assert route.call_count == initial_calls
    assert r1.cid == r2.cid


@respx.mock
def test_search_handles_missing_ghs_gracefully():
    pubchem.cache_clear()
    respx.get("https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/12345/property/" +
              pubchem.PROPERTIES + "/JSON").mock(
        return_value=Response(200, json=_props_response(cid=12345, MolecularFormula="C5H4N4O"))
    )
    respx.get("https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/12345/synonyms/JSON").mock(
        return_value=Response(200, json=_synonyms_response(["Hypoxanthine"]))
    )
    # GHS endpoint returns 404 (no data)
    respx.get("https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/12345/JSON").mock(
        return_value=Response(404)
    )

    result = pubchem.search("12345", query_type="cid")
    assert result.cid == 12345
    assert result.ghs_pictograms == []
    assert result.h_phrases == []
    assert result.p_phrases == []


def test_cache_stats():
    info = pubchem.cache_stats()
    assert "size" in info
    assert "maxsize" in info
    assert "ttl_seconds" in info


def test_cache_clear():
    pubchem.cache_clear()
    assert pubchem.cache_stats()["size"] == 0
