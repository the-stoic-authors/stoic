"""One-shot heal script for translations.

For IT: msgid is the source language, so any empty msgstr should mirror
the msgid. For EN: pre-populate empty msgstrs from msgid, then apply
the EN_FIXES dict to translate the new patch 10 strings.

Also handles ``#, fuzzy`` entries from ``pybabel update`` heuristic
matches: the fuzzy flag is dropped and the msgstr is overwritten with
the correct value (msgid for IT, EN_FIXES[msgid] when available for
EN — otherwise leave the existing fuzzy translation alone since it's
the best guess pybabel has).

Run from project root after `pybabel update`. After running, recompile
with `pybabel compile -d stoic_eln/translations`.
"""
from __future__ import annotations

import re
from pathlib import Path


# Manual EN translations for new patch-10 strings (and a few fallbacks
# for older strings that might still be untranslated). Anything not
# listed falls back to msgid := msgstr (acceptable for IT, harmless
# but not ideal for EN — the absent ones will at least be readable).
EN_FIXES: dict[str, str] = {
    # Attachments — new in patch 10
    "Allegati": "Attachments",
    "Allegato caricato.": "Attachment uploaded.",
    "NMR, HPLC, foto, dati strumentali":
        "NMR, HPLC, photos, instrument data",
    "schede tecniche, protocolli, riferimenti":
        "datasheets, protocols, references",
    "scheda di sicurezza, certificato d'analisi":
        "safety datasheet, certificate of analysis",
    "CoA, scheda lotto, etichetta…":
        "CoA, lot sheet, label…",
    "Nessun allegato. Carica il primo qui sotto.":
        "No attachments yet. Upload the first one below.",
    "caricato da": "uploaded by",
    "Scarica": "Download",
    "Elimina": "Delete",
    "Eliminare definitivamente \"%(f)s\"?":
        "Permanently delete \"%(f)s\"?",
    "Didascalia opzionale (es. NMR purificato)":
        "Optional caption (e.g. purified NMR)",
    "Carica": "Upload",
    "Massimo 100 MB. Tipi accettati: PDF, immagini, dati di laboratorio "
    "(csv, xlsx, jdx, mol, raw, mzML…), archivi (.zip).":
        "Max 100 MB. Allowed: PDF, images, lab data "
        "(csv, xlsx, jdx, mol, raw, mzML…), archives (.zip).",
    "Nessun file selezionato.": "No file selected.",
    "Tipo di file '.%(ext)s' non permesso (potenzialmente eseguibile).":
        "File type '.%(ext)s' not allowed (potentially executable).",
    "Tipo di file '.%(ext)s' non supportato. Tipi permessi: %(types)s.":
        "File type '.%(ext)s' not supported. Allowed types: %(types)s.",
    "File vuoto.": "Empty file.",
    "File troppo grande (%(size).1f MB). Massimo: %(max).0f MB.":
        "File too large (%(size).1f MB). Max: %(max).0f MB.",
    "entity_type non valido: %(t)s": "invalid entity_type: %(t)s",
    "Errore nel salvataggio del file: %(err)s":
        "Error while saving the file: %(err)s",
    "(utente eliminato)": "(deleted user)",
    # Labels — new in patch 12
    "Stampa etichetta": "Print label",
    "Lotto #%(id)d": "Lot #%(id)d",
    "Formato": "Format",
    "Copie": "Copies",
    "Numero di etichette identiche da stampare per questo lotto.":
        "Number of identical labels to print for this lot.",
    "Posizione di partenza sul foglio": "Start position on the sheet",
    "0 = primo slot in alto a sinistra. Utile per riusare un foglio "
    "Avery già parzialmente stampato — conta le celle già usate "
    "(sinistra→destra, riga per riga) e mettile qui.":
        "0 = top-left slot. Useful when reusing a partially-printed "
        "Avery sheet — count the cells already used (left→right, row by "
        "row) and put that here.",
    "Il QR contiene: lotto_id, batch, sostanza e scadenza in formato "
    "JSON. Sull'etichetta vengono stampati nome sostanza, batch, "
    "scadenza, CAS, formula, MW, densità, pittogrammi GHS e codici "
    "delle frasi H/P quando disponibili.":
        "The QR contains lotto_id, batch, substance and expiry as "
        "JSON. The label itself shows the substance name, batch, "
        "expiry date, CAS, formula, MW, density, GHS pictograms "
        "and H/P phrase codes when available.",
    "Genera PDF": "Generate PDF",
    "Annulla": "Cancel",
    "Scad": "Exp",
    "Formato etichetta non valido.": "Invalid label format.",
}


# Match a (multi-line) PO entry: optional reference/comment lines, then
# msgid block + msgstr block. We capture the comment block separately so
# we can drop ``#, fuzzy`` flags. The trailing blank line is preserved
# by leaving the match boundary before it.
ENTRY_RE = re.compile(
    r"((?:^#[^\n]*\n)*)"                         # comment / reference lines
    r"(msgid (?:\"[^\"]*\"\s*)+)"                # msgid block
    r"(msgstr (?:\"[^\"]*\"\s*)+)",              # msgstr block
    re.MULTILINE,
)


def _join_quoted(block: str) -> str:
    """Concatenate the contents of consecutive quoted lines in a PO block."""
    lines = block.splitlines()
    pieces: list[str] = []
    for line in lines:
        # Drop leading 'msgid '/'msgstr ' label, keep the quoted body.
        line = line.strip()
        if line.startswith("msgid"):
            line = line[len("msgid"):].lstrip()
        elif line.startswith("msgstr"):
            line = line[len("msgstr"):].lstrip()
        if line.startswith('"') and line.endswith('"'):
            # Decode escape sequences in the quoted segment.
            inner = line[1:-1]
            inner = inner.replace('\\"', '"').replace("\\n", "\n")
            inner = inner.replace("\\\\", "\\")
            pieces.append(inner)
    return "".join(pieces)


def _emit_msgstr(text: str) -> str:
    """Format a Python string as a PO msgstr block (single-line for short)."""
    encoded = (
        text.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
    )
    return f'msgstr "{encoded}"'


def _strip_fuzzy_flag(comments: str) -> tuple[str, bool]:
    """Remove ``#, fuzzy`` from a flag line, keep other flags intact.

    Returns the cleaned comment block and whether a fuzzy flag was present.
    """
    had_fuzzy = False
    out_lines: list[str] = []
    for line in comments.splitlines(keepends=True):
        if line.startswith("#,") and "fuzzy" in line:
            had_fuzzy = True
            # Keep other flags on the same line (e.g. python-format).
            stripped = line.lstrip("#,").strip()
            flags = [f.strip() for f in stripped.split(",")
                     if f.strip() and f.strip() != "fuzzy"]
            if flags:
                out_lines.append(f"#, {', '.join(flags)}\n")
            # else: drop the line entirely
        else:
            out_lines.append(line)
    return "".join(out_lines), had_fuzzy


def heal(po_path: Path, lang: str) -> tuple[int, int, int]:
    """Fill empty msgstr entries; apply EN_FIXES for English; clear fuzzy.

    Returns:
        (filled_from_id, applied_overrides, fuzzy_cleared)
    """
    text = po_path.read_text(encoding="utf-8")

    filled = 0
    overridden = 0
    fuzzy_cleared = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal filled, overridden, fuzzy_cleared
        comments = match.group(1)
        msgid_block = match.group(2)
        msgstr_block = match.group(3)
        msgid_text = _join_quoted(msgid_block)
        msgstr_text = _join_quoted(msgstr_block)

        # Skip the metadata header (empty msgid).
        if msgid_text == "":
            return match.group(0)

        cleaned_comments, had_fuzzy = _strip_fuzzy_flag(comments)
        if had_fuzzy:
            fuzzy_cleared += 1
            # Force-rebuild the msgstr from EN_FIXES (EN) or msgid (IT).
            if lang == "en" and msgid_text in EN_FIXES:
                overridden += 1
                new_msgstr = _emit_msgstr(EN_FIXES[msgid_text])
            elif lang == "it":
                # IT is source language: msgstr := msgid is correct.
                filled += 1
                new_msgstr = _emit_msgstr(msgid_text)
            else:
                # EN with no fix available: keep whatever pybabel guessed,
                # since stripping fuzzy without overriding leaves a usable
                # (if imperfect) translation.
                new_msgstr = msgstr_block.rstrip() + "\n"
                if not new_msgstr.startswith("msgstr"):
                    # safety: rebuild from current text
                    new_msgstr = _emit_msgstr(msgstr_text) + "\n"
            return cleaned_comments + msgid_block + new_msgstr.rstrip("\n") + "\n"

        # Non-fuzzy entries: only touch empty msgstrs (existing behaviour).
        if msgstr_text != "":
            # For EN: still allow EN_FIXES to override on demand if they
            # match an existing entry (useful if a previous pass put a
            # naive msgid:=msgstr fallback in place).
            if lang == "en" and msgid_text in EN_FIXES \
                    and msgstr_text != EN_FIXES[msgid_text]:
                overridden += 1
                return (cleaned_comments + msgid_block
                        + _emit_msgstr(EN_FIXES[msgid_text]) + "\n")
            return match.group(0)

        # Empty msgstr: fill it.
        if lang == "en" and msgid_text in EN_FIXES:
            overridden += 1
            new_msgstr = _emit_msgstr(EN_FIXES[msgid_text])
        else:
            filled += 1
            new_msgstr = _emit_msgstr(msgid_text)
        return cleaned_comments + msgid_block + new_msgstr + "\n"

    new_text = ENTRY_RE.sub(repl, text)
    po_path.write_text(new_text, encoding="utf-8")
    return filled, overridden, fuzzy_cleared


def main() -> None:
    base = Path("stoic_eln/translations")
    for lang in ("it", "en"):
        po = base / lang / "LC_MESSAGES" / "messages.po"
        if not po.exists():
            print(f"  skip: {po} missing")
            continue
        filled, overridden, fuzzy_cleared = heal(po, lang)
        print(f"  {lang}: filled={filled} overridden={overridden} "
              f"fuzzy_cleared={fuzzy_cleared}")


if __name__ == "__main__":
    main()
