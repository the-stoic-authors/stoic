"""Stoic ELN — Currency configuration (Settimana 6 patch 6.1).

The lab's currency is stored as an ISO 4217 three-letter code in the
``app.currency`` AppSetting. Default: EUR.

We render symbols for currencies that have a widely-recognised glyph,
and the three-letter code (with a thin space) for the others.

Example:
  format_currency(123.45) → "€ 123.45"   (EUR)
  format_currency(123.45) → "$ 123.45"   (USD)
  format_currency(123.45) → "UZS 123.45" (Uzbek so'm — no widely-used glyph)

Symbols are placed BEFORE the amount with a space (continental European
style). This is a deliberate choice: it works visually for all
languages we support and avoids ambiguity with thousand separators.
"""

from __future__ import annotations

from stoic_eln.models.settings import AppSetting


SETTING_KEY = "app.currency"
DEFAULT_CURRENCY = "EUR"


# Currencies with a widely-recognised glyph. For others, we fall back
# to the ISO code itself.
_SYMBOLS: dict[str, str] = {
    "EUR": "€",
    "USD": "$",
    "GBP": "£",
    "JPY": "¥",
    "CNY": "¥",         # Renminbi/Yuan
    "INR": "₹",
    "KRW": "₩",
    "CHF": "CHF",       # No symbol commonly used; show code
    "RUB": "₽",
    "TRY": "₺",
    "NGN": "₦",
    "ILS": "₪",
    "PHP": "₱",
    "VND": "₫",
    "BRL": "R$",
    "CAD": "CA$",
    "AUD": "A$",
    "NZD": "NZ$",
    "HKD": "HK$",
    "SGD": "S$",
    "MXN": "MX$",
    "ARS": "AR$",
    "PLN": "zł",
    "CZK": "Kč",
    "SEK": "kr",
    "NOK": "kr",
    "DKK": "kr",
    "HUF": "Ft",
    "THB": "฿",
}


# Common ISO codes shown in the dropdown UI. The user can also type
# any 3-letter code in the free-text field.
COMMON_CODES = [
    "EUR", "USD", "GBP", "CHF", "JPY", "CNY", "INR", "BRL",
    "CAD", "AUD", "NZD", "MXN", "SGD", "HKD", "KRW", "RUB", "TRY",
    "PLN", "CZK", "SEK", "NOK", "DKK", "HUF", "ILS", "ZAR",
]


def get_currency_code() -> str:
    """Return the configured ISO currency code, defaulting to EUR."""
    raw = AppSetting.get(SETTING_KEY, DEFAULT_CURRENCY) or DEFAULT_CURRENCY
    code = raw.strip().upper()
    if len(code) != 3 or not code.isalpha():
        return DEFAULT_CURRENCY
    return code


def set_currency_code(code: str) -> str:
    """Validate and store the currency code. Returns the cleaned value."""
    cleaned = (code or "").strip().upper()
    if len(cleaned) != 3 or not cleaned.isalpha():
        raise ValueError("Codice valuta non valido (servono 3 lettere ISO).")
    AppSetting.set(SETTING_KEY, cleaned)
    return cleaned


def currency_glyph(code: str | None = None) -> str:
    """Return the symbol for ``code``, or the code itself if no glyph."""
    c = (code or get_currency_code()).upper()
    return _SYMBOLS.get(c, c)


def format_currency(amount: float | None,
                    code: str | None = None,
                    *,
                    decimals: int = 2) -> str:
    """Format ``amount`` with the currency glyph (or code).

    Returns "—" for None. Uses standard decimal point with the
    requested number of decimals.
    """
    if amount is None:
        return "—"
    glyph = currency_glyph(code)
    return f"{glyph} {amount:.{decimals}f}"
