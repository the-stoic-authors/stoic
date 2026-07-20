"""Stoic ELN — PubChem integration service.

Fetches chemical data from the PUG-REST and PUG-View APIs.
Uses an in-memory TTL cache to reduce repeat lookups within a session.

Reference:
- PUG-REST: https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest
- PUG-View: https://pubchem.ncbi.nlm.nih.gov/docs/pug-view
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
from cachetools import TTLCache

logger = logging.getLogger(__name__)

# Cache: max 1000 entries, expire after 24h
_cache: TTLCache = TTLCache(maxsize=1000, ttl=86400)

PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUBCHEM_VIEW = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"
DEFAULT_TIMEOUT = 10.0

# Properties we request from PUG-REST.
#
# **Note on the SMILES fields**: PubChem deprecated the legacy
# ``CanonicalSMILES`` and ``IsomericSMILES`` properties in 2024–2025,
# replacing them with ``SMILES`` (full structure with stereochemistry —
# what was IsomericSMILES) and ``ConnectivitySMILES`` (the achiral
# connectivity-only form — what was CanonicalSMILES). Requesting the
# old names against the current API returns empty fields without any
# error code, which is what caused imported substances to silently
# arrive without a SMILES set.
#
# We request BOTH the new and the legacy names so the import works
# regardless of which the server happens to return. The parser at
# ``_fill_properties`` falls back through the same order. If PubChem
# reverts the rename or a proxy/mirror exposes only the old keys, we
# still pick up the value.
PROPERTIES = (
    "MolecularFormula,MolecularWeight,"
    "SMILES,ConnectivitySMILES,"
    "IsomericSMILES,CanonicalSMILES,"
    "InChI,InChIKey,IUPACName,XLogP"
)

# GHS pictogram code mapping (the URL Markup uses these signal-word images)
PICTOGRAM_KEYWORDS = {
    "Explosive": "GHS01",
    "Flammable": "GHS02",
    "Oxidizer": "GHS03",
    "Compressed Gas": "GHS04",
    "Corrosive": "GHS05",
    "Acute Toxic": "GHS06",
    "Irritant": "GHS07",
    "Health Hazard": "GHS08",
    "Environmental Hazard": "GHS09",
}


@dataclass
class PubChemResult:
    """Structured data extracted from PubChem for a single compound."""

    cid: int
    name: str | None = None
    iupac_name: str | None = None
    cas_number: str | None = None
    molecular_formula: str | None = None
    molecular_weight: float | None = None
    smiles: str | None = None
    inchi: str | None = None
    inchi_key: str | None = None
    melting_point_c: float | None = None
    boiling_point_c: float | None = None
    density: float | None = None
    state: str | None = None
    ghs_pictograms: list[str] = field(default_factory=list)
    h_phrases: list[str] = field(default_factory=list)
    p_phrases: list[str] = field(default_factory=list)


@dataclass
class PubChemCandidate:
    """Lightweight candidate for the disambiguation list.

    Only the fields needed to let the user pick the right compound:
    CID, name, molecular formula, and SMILES (for the client-side
    structure depiction). Full data is fetched later via ``search``
    once the user selects a CID.
    """

    cid: int
    name: str | None = None
    molecular_formula: str | None = None
    smiles: str | None = None


class PubChemError(Exception):
    """Raised when PubChem cannot be reached or returns an error."""


class PubChemNotFound(PubChemError):
    """Raised when no compound matches the query."""


def _detect_query_type(query: str) -> str:
    """Best-effort detection of input query type.

    Returns one of: 'cid', 'inchikey', 'inchi', 'smiles', 'cas', 'name'.
    """
    q = query.strip()
    if q.isdigit():
        return "cid"
    if re.fullmatch(r"[A-Z]{14}-[A-Z]{10}-[A-Z]", q):
        return "inchikey"
    if q.startswith("InChI="):
        return "inchi"
    if re.fullmatch(r"\d{1,7}-\d{2}-\d", q):
        return "cas"
    # Crude SMILES detection: contains typical SMILES chars but isn't a name
    smiles_chars = set("()[]=#%+-./0123456789@\\")
    if any(c in smiles_chars for c in q) and not re.search(r"\s", q):
        return "smiles"
    return "name"


def _client(timeout: float = DEFAULT_TIMEOUT) -> httpx.Client:
    return httpx.Client(timeout=timeout, follow_redirects=True)


def search(query: str, query_type: str | None = None) -> PubChemResult:
    """Search PubChem and return parsed compound data.

    Args:
        query: CAS, name, SMILES, InChI, InChIKey, or CID.
        query_type: Optional override; otherwise auto-detected.

    Raises:
        PubChemNotFound: if no compound matches.
        PubChemError: for any other failure.
    """
    cache_key = f"search:{query_type or 'auto'}:{query}"
    if cache_key in _cache:
        logger.debug("PubChem cache hit: %s", cache_key)
        return _cache[cache_key]

    qtype = query_type or _detect_query_type(query)
    cid = _resolve_to_cid(query, qtype)

    result = PubChemResult(cid=cid)
    _fill_properties(result)
    _fill_synonyms(result)
    _fill_ghs(result)
    _fill_experimental_properties(result)
    _derive_state(result)

    _cache[cache_key] = result
    return result


def _resolve_to_cid(query: str, qtype: str) -> int:
    """Convert a query into a single PubChem CID (the first match)."""
    return _resolve_to_cids(query, qtype)[0]


def _resolve_to_cids(query: str, qtype: str) -> list[int]:
    """Convert a query into the full list of matching PubChem CIDs.

    For unambiguous queries (CID, InChIKey, CAS) this is usually a
    single element; for names it can be several (isomers, salts, …).
    """
    if qtype == "cid":
        return [int(query)]

    type_path = {
        "inchikey": ("inchikey", query),
        "name": ("name", query),
        "cas": ("name", query),
        "smiles": ("smiles", query),
        "inchi": ("inchi", query),
    }
    if qtype not in type_path:
        raise PubChemError(f"Unsupported query type: {qtype!r}")

    namespace, value = type_path[qtype]
    url = f"{PUBCHEM_BASE}/compound/{namespace}/{value}/cids/JSON"

    try:
        with _client() as c:
            r = c.get(url)
    except httpx.HTTPError as e:
        raise PubChemError(f"PubChem unreachable: {e}") from e

    if r.status_code == 404:
        raise PubChemNotFound(f"No compound found for {qtype}: {query!r}")
    if r.status_code != 200:
        raise PubChemError(f"PubChem returned HTTP {r.status_code}")

    data = r.json()
    cids = data.get("IdentifierList", {}).get("CID", [])
    if not cids:
        raise PubChemNotFound(f"No CID for {qtype}: {query!r}")
    return list(cids)


def _resolve_name_isomer_cids(query: str, qtype: str, scan: int = 200) -> list[int]:
    """Resolve a NAME query to the CIDs of same-formula isomers.

    PubChem has no "give me the stereoisomers of X" endpoint, so we
    approximate it:
      1. Resolve the canonical match (name_type=complete) → 1 CID +
         its molecular formula.
      2. Broaden with name_type=word → every CID whose name contains
         the query (thousands, mostly unrelated derivatives).
      3. Keep only those whose molecular formula equals the canonical
         one — i.e. true isomers/stereoisomers (e.g. all C6H12O6 for
         "glucose": glucose anomers, mannose, galactose, …).

    The canonical CID is always placed first. Falls back to just the
    canonical CID if anything in the broadening step fails.
    """
    # 1. Canonical match + its formula.
    canonical = _resolve_to_cids(query, qtype)  # complete match
    canon_cid = canonical[0]
    canon_formula = None
    try:
        with _client() as c:
            r = c.get(f"{PUBCHEM_BASE}/compound/cid/{canon_cid}/property/MolecularFormula/JSON")
        if r.status_code == 200:
            props = r.json().get("PropertyTable", {}).get("Properties", [])
            if props:
                canon_formula = props[0].get("MolecularFormula")
    except httpx.HTTPError:
        return [canon_cid]

    if not canon_formula:
        return [canon_cid]

    # 2. Broaden with name_type=word.
    namespace = "name"
    url = f"{PUBCHEM_BASE}/compound/{namespace}/{query}/cids/JSON"
    try:
        with _client() as c:
            r = c.get(url, params={"name_type": "word"})
    except httpx.HTTPError:
        return [canon_cid]
    if r.status_code != 200:
        return [canon_cid]
    word_cids = r.json().get("IdentifierList", {}).get("CID", [])
    if not word_cids:
        return [canon_cid]

    # 3. Filter the first `scan` CIDs by matching molecular formula.
    scan_cids = word_cids[:scan]
    cid_list = ",".join(str(c) for c in scan_cids)
    try:
        with _client() as c:
            r = c.get(f"{PUBCHEM_BASE}/compound/cid/{cid_list}/property/MolecularFormula/JSON")
    except httpx.HTTPError:
        return [canon_cid]
    if r.status_code != 200:
        return [canon_cid]

    matching = [
        int(row["CID"])
        for row in r.json().get("PropertyTable", {}).get("Properties", [])
        if row.get("MolecularFormula") == canon_formula
    ]

    # Canonical CID first, then the rest (dedup, preserve order).
    ordered = [canon_cid] + [c for c in matching if c != canon_cid]
    seen: set[int] = set()
    result: list[int] = []
    for c in ordered:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result


def search_candidates(
    query: str, query_type: str | None = None, limit: int = 12
) -> list[PubChemCandidate]:
    """Return a list of candidate compounds matching *query*.

    Resolves the query to CIDs, then fetches name + molecular formula
    + SMILES for all of them in a SINGLE batch PUG-REST call (CIDs are
    comma-separated in the URL), so the disambiguation list — including
    client-side structure depictions — loads with one request.

    Raises PubChemNotFound / PubChemError like ``search``.
    """
    cache_key = f"candidates:{query_type or 'auto'}:{query}:{limit}"
    if cache_key in _cache:
        return _cache[cache_key]

    qtype = query_type or _detect_query_type(query)

    # For NAME/CAS searches, resolve to same-formula isomers so the
    # user can distinguish stereoisomers. Other query types (CID,
    # InChIKey, SMILES, InChI) are unambiguous → single result.
    if qtype in ("name", "cas"):
        cids = _resolve_name_isomer_cids(query, qtype)[:limit]
    else:
        cids = _resolve_to_cids(query, qtype)[:limit]

    # Batch property fetch for all CIDs at once.
    cid_list = ",".join(str(c) for c in cids)
    url = (
        f"{PUBCHEM_BASE}/compound/cid/{cid_list}"
        f"/property/MolecularFormula,SMILES,ConnectivitySMILES,IUPACName/JSON"
    )
    props_by_cid: dict[int, dict] = {}
    try:
        with _client() as c:
            r = c.get(url)
        if r.status_code == 200:
            rows = r.json().get("PropertyTable", {}).get("Properties", [])
            for row in rows:
                props_by_cid[int(row.get("CID"))] = row
    except httpx.HTTPError as e:
        raise PubChemError(f"PubChem unreachable: {e}") from e

    # Fetch a display name (first synonym) for each CID in one batch call.
    names_by_cid = _batch_synonyms(cids)

    candidates: list[PubChemCandidate] = []
    for cid in cids:
        props = props_by_cid.get(cid, {})
        smiles = props.get("SMILES") or props.get("ConnectivitySMILES")
        candidates.append(
            PubChemCandidate(
                cid=cid,
                name=names_by_cid.get(cid) or props.get("IUPACName"),
                molecular_formula=props.get("MolecularFormula"),
                smiles=smiles,
            )
        )

    _cache[cache_key] = candidates
    return candidates


def _batch_synonyms(cids: list[int]) -> dict[int, str]:
    """Fetch the first synonym (common name) for each CID in one call."""
    if not cids:
        return {}
    cid_list = ",".join(str(c) for c in cids)
    url = f"{PUBCHEM_BASE}/compound/cid/{cid_list}/synonyms/JSON"
    out: dict[int, str] = {}
    try:
        with _client() as c:
            r = c.get(url)
        if r.status_code == 200:
            entries = r.json().get("InformationList", {}).get("Information", [])
            for entry in entries:
                cid = int(entry.get("CID"))
                syns = entry.get("Synonym", [])
                if syns:
                    out[cid] = syns[0]
    except httpx.HTTPError:
        # Names are best-effort; fall back to IUPAC in the caller.
        pass
    return out


def _fill_properties(result: PubChemResult) -> None:
    """Fetch core molecular properties via PUG-REST."""
    url = f"{PUBCHEM_BASE}/compound/cid/{result.cid}/property/{PROPERTIES}/JSON"
    try:
        with _client() as c:
            r = c.get(url)
            r.raise_for_status()
        data = r.json()
        props = data["PropertyTable"]["Properties"][0]
    except (httpx.HTTPError, KeyError, IndexError) as e:
        logger.warning("PubChem properties lookup failed for CID %s: %s", result.cid, e)
        return

    result.molecular_formula = props.get("MolecularFormula")
    mw = props.get("MolecularWeight")
    if mw is not None:
        try:
            result.molecular_weight = float(mw)
        except (TypeError, ValueError):
            pass
    # Pick the most informative SMILES available, preferring the
    # stereo-aware form when present:
    #   1. ``SMILES``           — current name for stereo-aware form
    #   2. ``IsomericSMILES``   — legacy name for stereo-aware form
    #   3. ``ConnectivitySMILES`` — current name for achiral form
    #   4. ``CanonicalSMILES``  — legacy name for achiral form
    # All four keys are requested in PROPERTIES; the server returns
    # whichever it knows about and we take the first non-empty hit.
    # Empty strings count as missing, hence ``or`` chain.
    result.smiles = (
        props.get("SMILES")
        or props.get("IsomericSMILES")
        or props.get("ConnectivitySMILES")
        or props.get("CanonicalSMILES")
    )
    result.inchi = props.get("InChI")
    result.inchi_key = props.get("InChIKey")
    result.iupac_name = props.get("IUPACName")


def _fill_synonyms(result: PubChemResult) -> None:
    """Fetch the first available CAS-like synonym and a friendly name."""
    url = f"{PUBCHEM_BASE}/compound/cid/{result.cid}/synonyms/JSON"
    try:
        with _client() as c:
            r = c.get(url)
            r.raise_for_status()
        data = r.json()
        synonyms = data["InformationList"]["Information"][0].get("Synonym", [])
    except (httpx.HTTPError, KeyError, IndexError) as e:
        logger.warning("PubChem synonyms lookup failed for CID %s: %s", result.cid, e)
        return

    # Find the first plausible CAS number
    for s in synonyms:
        if re.fullmatch(r"\d{1,7}-\d{2}-\d", s):
            result.cas_number = s
            break

    # First "common" name (short, no special chars) as the display name
    if not result.name:
        for s in synonyms:
            if 2 <= len(s) <= 60 and " " not in s.strip()[-3:]:
                # Skip strings that look like InChIKeys, IDs, registry numbers
                if re.fullmatch(r"[A-Z0-9\-]+", s) and len(s) > 12:
                    continue
                result.name = s
                break
    if not result.name and synonyms:
        result.name = synonyms[0]


def _fill_ghs(result: PubChemResult) -> None:
    """Fetch GHS classification data from PUG-View."""
    url = f"{PUBCHEM_VIEW}/data/compound/{result.cid}/JSON?heading=GHS+Classification"
    try:
        with _client() as c:
            r = c.get(url)
        if r.status_code == 404:
            return  # No GHS data
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as e:
        logger.warning("PubChem GHS lookup failed for CID %s: %s", result.cid, e)
        return

    pictograms: set[str] = set()
    h_codes: set[str] = set()
    p_codes: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            # Pictogram URLs (Markup items with Type "Icon" pointing to GHS images)
            url = node.get("URL")
            if url and isinstance(url, str):
                # Look for GHS01-09 in URL
                m = re.search(r"GHS0\d", url, re.IGNORECASE)
                if m:
                    pictograms.add(m.group(0).upper())

            # Pictogram by description text
            for key in ("Description", "Extra"):
                v = node.get(key)
                if isinstance(v, str):
                    for keyword, code in PICTOGRAM_KEYWORDS.items():
                        if keyword.lower() in v.lower():
                            pictograms.add(code)

            # Phrase strings inside any String field (regex extracts H/P/EUH codes)
            for key, val in node.items():
                if key == "String" and isinstance(val, str):
                    # Map common pictogram-keyword strings to codes too
                    for keyword, code in PICTOGRAM_KEYWORDS.items():
                        if keyword.lower() in val.lower():
                            pictograms.add(code)
                    # Match composed phrases first (P301+P330+P331),
                    # falling back to single phrases. This preserves
                    # the EU CLP "linked" P-statements where the
                    # full meaning depends on reading them together:
                    # "IF SWALLOWED + Rinse mouth + Do NOT induce
                    # vomiting" is one instruction, not three.
                    pat = (
                        r"\b("
                        r"(?:H\d{3}|EUH\d{3}|P\d{3})"
                        r"(?:\+(?:H\d{3}|EUH\d{3}|P\d{3}))*"
                        r")\b"
                    )
                    for m in re.finditer(pat, val):
                        code = m.group(1)
                        # Classify by the first segment's prefix.
                        first = code.split("+", 1)[0]
                        if first.startswith("P"):
                            p_codes.add(code)
                        else:
                            h_codes.add(code)
                walk(val)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    result.ghs_pictograms = sorted(pictograms)
    result.h_phrases = sorted(h_codes)
    result.p_phrases = sorted(p_codes)


def _fill_experimental_properties(result: PubChemResult) -> None:
    """Fetch MP/BP/density from the 'Experimental Properties' section."""
    headings = {
        "Melting Point": "melting_point_c",
        "Boiling Point": "boiling_point_c",
        "Density": "density",
    }
    for heading, attr in headings.items():
        value = _fetch_experimental_value(result.cid, heading)
        if value is not None:
            setattr(result, attr, value)


def _fetch_experimental_value(cid: int, heading: str) -> float | None:
    """Try to extract a numeric value from a PubChem experimental section."""
    encoded_heading = heading.replace(" ", "+")
    url = f"{PUBCHEM_VIEW}/data/compound/{cid}/JSON?heading={encoded_heading}"
    try:
        with _client() as c:
            r = c.get(url)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as e:
        logger.debug("PubChem %s lookup failed for CID %s: %s", heading, cid, e)
        return None

    # Walk JSON looking for "Number" arrays
    def find_numbers(node: Any) -> list[float]:
        out: list[float] = []
        if isinstance(node, dict):
            if "Number" in node and isinstance(node["Number"], list):
                for n in node["Number"]:
                    try:
                        out.append(float(n))
                    except (TypeError, ValueError):
                        pass
            for v in node.values():
                out.extend(find_numbers(v))
        elif isinstance(node, list):
            for item in node:
                out.extend(find_numbers(item))
        return out

    nums = find_numbers(data)
    if not nums:
        # Try parsing strings like "78.37 °C" from "StringWithMarkup"
        nums = _parse_strings_for_numbers(data, heading)
    if not nums:
        return None

    # Return median to reject outliers from old/wrong measurements
    nums.sort()
    return nums[len(nums) // 2]


def _parse_strings_for_numbers(data: Any, heading: str) -> list[float]:
    """Extract first numeric value from String fields, converting °F to °C if needed."""
    out: list[float] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "String" in node and isinstance(node["String"], str):
                s = node["String"]
                # Match "78.37 °C" or "173 F" or "1.234 g/cm3"
                m = re.match(r"\s*(-?\d+\.?\d*)\s*°?\s*([CF])?", s)
                if m:
                    try:
                        v = float(m.group(1))
                        unit = m.group(2)
                        # Convert F to C for temperature-related headings
                        if unit == "F" and "Point" in heading:
                            v = (v - 32) * 5 / 9
                        out.append(v)
                    except (TypeError, ValueError):
                        pass
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return out


def _derive_state(result: PubChemResult) -> None:
    """Determine physical state at 25°C from MP/BP."""
    if result.state:
        return
    room_temp = 25.0
    if result.melting_point_c is not None and result.melting_point_c > room_temp:
        result.state = "solid"
    elif result.boiling_point_c is not None and result.boiling_point_c < room_temp:
        result.state = "gas"
    elif (
        result.melting_point_c is not None
        and result.boiling_point_c is not None
        and result.melting_point_c <= room_temp <= result.boiling_point_c
    ):
        result.state = "liquid"


def cache_stats() -> dict:
    """Return cache statistics (for /admin/diagnostics)."""
    return {
        "size": len(_cache),
        "maxsize": _cache.maxsize,
        "ttl_seconds": _cache.ttl,
    }


def cache_clear() -> None:
    """Clear the cache (called from admin UI in Week 5)."""
    _cache.clear()
