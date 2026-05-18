"""One-shot: rebuild IT .po so every msgstr = msgid.

Italian IS the source language for Stoic, so for IT the correct
translation is always the literal msgid. ``pybabel update`` left
many entries with wrong fuzzy-derived translations from semantic
neighbours (e.g. msgid="Soluzione" → msgstr="solido"); this script
fixes that in one pass.

Preserves comments (``#:`` location refs, ``#,`` flags) so
maintainability is intact. Drops the ``fuzzy`` flag where present
since after this run the entry is no longer a guess.

Output: rewrites the input file in place. Run once after ``pybabel
update``. Then ``pybabel compile``.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def fix_it_po(path: Path) -> tuple[int, int, int]:
    """Rewrite the IT .po file so msgstr == msgid for every entry.

    Returns:
        (fixed_wrong, filled_empty, unchanged) counts.
    """
    text = path.read_text(encoding="utf-8")

    # Split on blank lines to get entries. Keep the header (first block)
    # intact.
    blocks = re.split(r"\n\n", text)
    if not blocks:
        return (0, 0, 0)

    fixed_wrong = 0
    filled_empty = 0
    unchanged = 0
    new_blocks: list[str] = []

    for idx, block in enumerate(blocks):
        # Header block has empty msgid + Content-Type info. Leave alone.
        if idx == 0:
            new_blocks.append(block)
            continue

        # Skip obsolete blocks (start with ``#~``) — leave them as-is.
        if block.strip().startswith("#~"):
            new_blocks.append(block)
            continue

        if "msgid " not in block or "msgstr " not in block:
            new_blocks.append(block)
            continue

        # Parse msgid + msgstr (possibly multi-line)
        msgid = _extract_string(block, "msgid")
        msgstr = _extract_string(block, "msgstr")

        if msgid is None:
            new_blocks.append(block)
            continue

        if msgstr == msgid:
            unchanged += 1
            new_blocks.append(block)
            continue

        if msgstr == "":
            filled_empty += 1
        else:
            fixed_wrong += 1

        # Replace the msgstr with a clean single-line msgstr = msgid.
        # Use double-quote escape on the string.
        encoded = _po_string_encode(msgid)
        new_block = _replace_msgstr(block, encoded)

        # Drop the fuzzy flag if present — entry is now exact.
        new_block = _drop_fuzzy(new_block)

        new_blocks.append(new_block)

    out = "\n\n".join(new_blocks)
    if not out.endswith("\n"):
        out += "\n"
    path.write_text(out, encoding="utf-8")
    return fixed_wrong, filled_empty, unchanged


def _extract_string(block: str, keyword: str) -> str | None:
    """Extract the value following 'msgid' or 'msgstr' from a block.

    Handles continuation lines: msgid "a" "b" → "ab".
    """
    pattern = rf'^{re.escape(keyword)} (".*"(?:\s*\n".*")*)'
    m = re.search(pattern, block, re.MULTILINE)
    if not m:
        return None
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))
    # Unescape \" and \\ to get the raw string
    return "".join(p.replace('\\"', '"').replace("\\\\", "\\")
                   .replace("\\n", "\n").replace("\\t", "\t")
                   for p in parts)


def _po_string_encode(s: str) -> str:
    """Encode a Python string as a PO double-quoted literal.

    Handles \\, ", and newlines. If the string contains a newline,
    splits into multi-line msgstr "...\\n" continuation.
    """
    # Standard PO escapes
    escaped = (s.replace("\\", "\\\\")
                .replace('"', '\\"')
                .replace("\t", "\\t"))
    if "\n" not in escaped:
        return f'"{escaped}"'
    # Multi-line: each line ends with \n, gets its own quoted line,
    # and the whole thing starts with an empty "" so gettext folds
    # them in order.
    lines = escaped.split("\n")
    out = ['""']
    for line in lines[:-1]:
        out.append(f'"{line}\\n"')
    if lines[-1]:
        out.append(f'"{lines[-1]}"')
    return "\n".join(out)


def _replace_msgstr(block: str, new_msgstr_literal: str) -> str:
    """Replace the existing msgstr (including continuation lines)
    with a fresh one."""
    # Match: msgstr "..." possibly followed by ""..."" continuation lines
    pattern = r'^msgstr (".*"(?:\s*\n".*")*)'
    return re.sub(
        pattern,
        f"msgstr {new_msgstr_literal}",
        block,
        count=1,
        flags=re.MULTILINE,
    )


def _drop_fuzzy(block: str) -> str:
    """Remove the ``fuzzy`` flag from any ``#,`` line, removing the
    line entirely if fuzzy was the only flag."""
    out_lines = []
    for line in block.split("\n"):
        if line.startswith("#,"):
            flags = [f.strip() for f in line[2:].split(",")]
            flags = [f for f in flags if f and f != "fuzzy"]
            if flags:
                out_lines.append("#, " + ", ".join(flags))
            # else: drop the line entirely
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


if __name__ == "__main__":
    po = Path("stoic_eln/translations/it/LC_MESSAGES/messages.po")
    fixed, filled, unchanged = fix_it_po(po)
    print(f"Fixed wrong translations: {fixed}")
    print(f"Filled empty translations: {filled}")
    print(f"Unchanged (already correct): {unchanged}")
    print(f"Total: {fixed + filled + unchanged}")
