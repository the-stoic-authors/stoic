"""Stoic — Lightweight markdown renderer (Settimana 6 patch 9).

A minimal CommonMark-like renderer for note bodies. We don't pull
in a full markdown library because:

  - we only need a small subset of features (bold, italic, code,
    links, lists, line breaks)
  - inputs are always escaped first, so no raw HTML is ever rendered
  - keeping the dependency surface small is part of the project's
    "Stoic" design philosophy

Input: arbitrary user-typed text.
Output: HTML safe to insert into a page (already escaped).

Supported syntax:

  **bold**       → <strong>bold</strong>
  *italic*       → <em>italic</em>
  `code`         → <code>code</code>
  [text](url)    → <a href="url" rel="noopener" target="_blank">text</a>
                   (only http/https URLs allowed; others rendered as text)
  - item         → unordered list (one level only)
  1. item        → ordered list (one level only)
  blank line     → paragraph break
  single newline → <br>

Anything not matching becomes plain text (already HTML-escaped).
Raw HTML in the input is ALWAYS escaped — we never trust user input.
"""

from __future__ import annotations

import re
from html import escape


# ── Inline formatting ──────────────────────────────────────────────


_LINK_RE = re.compile(
    r"\[([^\]\n]+)\]\(([^)\s]+)\)",  # [text](url) — url must not contain spaces
)
_BOLD_RE = re.compile(r"\*\*([^\n*]+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)([^\n*]+?)(?<!\*)\*(?!\*)")
_CODE_RE = re.compile(r"`([^`\n]+)`")


def _safe_url(url: str) -> str | None:
    """Allow only absolute http/https URLs. Return None for anything else."""
    url = url.strip()
    if url.startswith(("http://", "https://", "mailto:")):
        return url
    return None


def _render_inline(text: str) -> str:
    """Render inline formatting on already-escaped text.

    Order matters: code first (to protect backticks from other parsing),
    then links, then bold (** before *), then italic.
    """
    # Code: temporarily replace with sentinel so * inside backticks isn't bold
    code_segments: list[str] = []

    def _save_code(m: re.Match) -> str:
        code_segments.append(m.group(1))
        return f"\x00CODE{len(code_segments) - 1}\x00"

    text = _CODE_RE.sub(_save_code, text)

    # Links — validate URL, fall back to plain text if invalid
    def _link_repl(m: re.Match) -> str:
        label, url = m.group(1), m.group(2)
        # label and url are already HTML-escaped at this stage
        safe = _safe_url(url)
        if safe is None:
            return f"[{label}]({url})"  # leave literal
        return (
            f'<a href="{safe}" target="_blank" '
            f'rel="noopener noreferrer">{label}</a>'
        )

    text = _LINK_RE.sub(_link_repl, text)

    # Bold (must come before italic)
    text = _BOLD_RE.sub(r"<strong>\1</strong>", text)
    # Italic
    text = _ITALIC_RE.sub(r"<em>\1</em>", text)

    # Restore code segments
    def _restore_code(m: re.Match) -> str:
        idx = int(m.group(1))
        return f"<code>{code_segments[idx]}</code>"

    text = re.sub(r"\x00CODE(\d+)\x00", _restore_code, text)
    return text


# ── Block-level parsing ────────────────────────────────────────────


_UL_LINE = re.compile(r"^\s*[-*]\s+(.*)$")
_OL_LINE = re.compile(r"^\s*\d+\.\s+(.*)$")


def render_markdown(src: str) -> str:
    """Render the given markdown source to safe HTML.

    Returns an empty string for empty / whitespace-only input.
    """
    if not src or not src.strip():
        return ""

    # Step 1: HTML-escape everything. From now on, only our own tag
    # insertions can produce raw HTML. User input cannot.
    src = escape(src, quote=False)

    # Step 2: split into blocks separated by blank lines
    blocks: list[str] = []
    current: list[str] = []
    for line in src.splitlines():
        if line.strip() == "":
            if current:
                blocks.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current))

    # Step 3: render each block
    out: list[str] = []
    for block in blocks:
        lines = block.split("\n")

        # Unordered list?
        if all(_UL_LINE.match(ln) for ln in lines):
            items = [_UL_LINE.match(ln).group(1) for ln in lines]
            html_items = "".join(
                f"<li>{_render_inline(it)}</li>" for it in items
            )
            out.append(f"<ul>{html_items}</ul>")
            continue

        # Ordered list?
        if all(_OL_LINE.match(ln) for ln in lines):
            items = [_OL_LINE.match(ln).group(1) for ln in lines]
            html_items = "".join(
                f"<li>{_render_inline(it)}</li>" for it in items
            )
            out.append(f"<ol>{html_items}</ol>")
            continue

        # Plain paragraph: inline formatting + <br> for single newlines
        rendered = _render_inline(block)
        rendered = rendered.replace("\n", "<br>")
        out.append(f"<p>{rendered}</p>")

    return "".join(out)
