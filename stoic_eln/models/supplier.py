"""Supplier — contact book entry for reagent/chemical suppliers.

Stores contact details (phone, email, website) and optional login
credentials for the supplier's online ordering portal. The password
field is stored in plain text; the database is protected at rest by
LUKS encryption on the server.
"""

from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from stoic_eln.extensions import db


class Supplier(db.Model):
    """A supplier in the lab's contact book."""

    __tablename__ = "supplier"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    portal_username: Mapped[str | None] = mapped_column(String(120), nullable=True)
    portal_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Back-reference to orders
    orders: Mapped[list] = relationship("Order", back_populates="supplier_ref", lazy="select")

    def __repr__(self) -> str:
        return f"<Supplier #{self.id} {self.name!r}>"
