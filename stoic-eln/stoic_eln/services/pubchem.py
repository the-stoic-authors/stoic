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

# Properties we request from PUG-REST
PROPERTIES = (
    "MolecularFormula,MolecularWeight,CanonicalSMILES,IsomericSMILES,"
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
    """Convert a query into a PubChem CID."""
    if qtype == "cid":
        return int(query)

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
    return cids[0]


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
    result.smiles = props.get("IsomericSMILES") or props.get("CanonicalSMILES")
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
                    for m in re.finditer(r"\b(H\d{3}|EUH\d{3}|P\d{3})\b", val):
                        code = m.group(1)
                        if code.startswith("P"):
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
