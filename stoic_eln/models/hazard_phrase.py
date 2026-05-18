"""Stoic ELN — HazardPhrase model.

Stores the official text of GHS hazard (H) and precautionary (P) phrases
in the languages we support (currently IT and EN). Populated once at first
boot from official sources, never edited at runtime.

This means PubChem can return just codes ("H225") and we render the full
text in the user's language without round-trips.
"""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from stoic_eln.extensions import db


class HazardPhrase(db.Model):
    """A single H or P phrase with its text in supported languages."""

    __tablename__ = "hazard_phrase"

    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    """E.g. 'H225', 'H319', 'P102', 'EUH001'."""

    category: Mapped[str] = mapped_column(String(8), nullable=False)
    """'H', 'P', or 'EUH'."""

    text_en: Mapped[str] = mapped_column(Text, nullable=False)
    text_it: Mapped[str] = mapped_column(Text, nullable=False)

    def __repr__(self) -> str:
        return f"<HazardPhrase {self.code}>"

    def text(self, locale: str) -> str:
        """Return the localized text for ``locale`` ('it' or 'en')."""
        if locale == "it":
            return self.text_it
        return self.text_en
