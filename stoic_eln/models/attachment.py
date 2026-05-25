"""Stoic — Attachment model (Settimana 6 patch 10).

A file attached to a Run, Reaction (template), Substance, or InventoryItem.
Generic association via (entity_type, entity_id), mirroring the Note model.

Files live on the filesystem under config['ATTACHMENTS_DIR'], with names
shaped as ``{sha256[:16]}_{safe_filename}``. Two rows pointing at the same
sha256 will share a single on-disk file (cheap dedup): the file is removed
only when the *last* Attachment row referencing it is deleted.

Hard delete (no soft-delete). The audit log preserves the history of
create/delete events.
"""

from __future__ import annotations

from datetime import datetime, UTC

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from stoic_eln.extensions import db


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# Allowed entity types for attachments. Centralised so routes/services can
# validate user-provided values against this whitelist. Includes
# inventory_item, which Note doesn't have — labels and CoAs need to live
# on the lot, not just on the substance.
ATTACHMENT_ENTITY_TYPES: tuple[str, ...] = (
    "run", "reaction", "substance", "inventory_item",
    # Added in patch 14.4: attachments on mixture recipes (Mixture)
    # and on individual preparation events (MixturePrep). Examples:
    # photo of a buffer recipe annotated by hand, CoA of a prepared
    # eluent batch, calibration spectrum of a stock solution.
    "mixture", "mixture_prep",
)


class Attachment(db.Model):
    """A file attached to a Run/Reaction/Substance/InventoryItem."""

    __tablename__ = "attachment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Generic association to the parent entity.
    entity_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True,
    )
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # Display name shown to users — what they uploaded as. Sanitised at
    # save time to remove path components and dangerous characters but
    # preserved in spirit (e.g. "NMR purificato.pdf" → kept as-is).
    filename: Mapped[str] = mapped_column(String(255), nullable=False)

    # On-disk filename: ``{sha256[:16]}_{safe_filename}``. Two rows can
    # point at the same storage_filename (dedup): the service layer makes
    # sure we only delete the file when the last row referencing it goes.
    storage_filename: Mapped[str] = mapped_column(String(320), nullable=False)

    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    # Full sha256 hex of the file content. Used for dedup and integrity
    # checks. 64 chars (lowercase hex) — a String(64) column is enough.
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Optional human-readable caption (e.g. "NMR purificato dopo colonna").
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)

    uploaded_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now_utc, nullable=False, index=True,
    )

    # Relationships
    uploaded_by = relationship("User", lazy="joined")

    __table_args__ = (
        # Common query: "all attachments on this entity, oldest first" —
        # used by the detail pages and the partial.
        Index(
            "ix_attachment_entity_created",
            "entity_type", "entity_id", "created_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Attachment #{self.id} {self.filename!r} "
            f"on {self.entity_type}#{self.entity_id}>"
        )

    # ── Convenience properties ────────────────────────────────────────

    @property
    def size_human(self) -> str:
        """Human-readable size, e.g. '1.4 MB' or '342 kB'."""
        size = self.size_bytes
        if size is None:
            return "—"
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.0f} kB"
        if size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        return f"{size / (1024 * 1024 * 1024):.2f} GB"

    @property
    def is_image(self) -> bool:
        return bool(self.mime_type and self.mime_type.startswith("image/"))

    @property
    def is_pdf(self) -> bool:
        return self.mime_type == "application/pdf"

    @property
    def extension(self) -> str:
        """Lowercase extension without the dot, or '' if none."""
        if "." not in self.filename:
            return ""
        return self.filename.rsplit(".", 1)[-1].lower()
