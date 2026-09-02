"""Mixture and MixtureComponent — physical preparations stored in lab.

A ``Substance`` represents a pure chemical entity (one InChIKey, one
molecule). A ``Mixture`` represents a *physical* preparation found on
a shelf: a buffer, a chromatography eluent, an HCl solution at a
specific normality, etc. The same pure ``Substance`` can underpin
many distinct ``Mixture`` rows — HCl 12N stock, HCl 1N working
solution, HCl 6N for workups — without violating the InChIKey
uniqueness on ``Substance``.

Composition is *optional*: a ``Mixture`` with zero
``MixtureComponent`` rows is the "quick label" case ("HCl 1N" with
just a name and a normality, no formal composition tracked). The
schema accommodates both the quick path and the structured path so a
mixture started as a quick label can later be enriched with a
detailed composition without recreating the record.

Lots (``InventoryItem``) attach to either a ``Substance`` (pure
reagent like a bottle of NaCl) or a ``Mixture`` (a prepared eluent
or a commercial solution). Exactly one of the two FKs must be set —
this is enforced as a CHECK constraint at migration time.

GHS safety data (pictograms, H/P phrases) on a ``Mixture`` defaults
to a derived view from the components but can be overridden manually
when the bench reality differs from a naïve union (e.g. a 0.01 M
NaOH solution behaves like water, not like sodium hydroxide).
"""

from __future__ import annotations

from datetime import datetime, UTC

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from stoic_eln.extensions import db
from typing import TYPE_CHECKING

from stoic_eln.models.substance import Substance

if TYPE_CHECKING:
    from stoic_eln.models.inventory import InventoryItem


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ── Mixture kinds ─────────────────────────────────────────────────────
#
# Free-form labels with a fixed canonical set; used for filtering and
# for tailoring the form UI (a "buffer" prompts for pH, an "eluent"
# defaults to %v/v on its components, etc — all UI-side, the model
# itself just stores the string).

MIXTURE_KIND_SOLUTION = "solution"  # HCl 1N, NaOH 0.5 M, brine
MIXTURE_KIND_ELUENT = "eluent"  # 95:5 hexane:EtOAc
MIXTURE_KIND_BUFFER = "buffer"  # phosphate buffer pH 7.4
MIXTURE_KIND_REAGENT_MIX = "reagent_mix"  # any other prepared reagent
MIXTURE_KIND_OTHER = "other"

MIXTURE_KINDS = (
    MIXTURE_KIND_SOLUTION,
    MIXTURE_KIND_ELUENT,
    MIXTURE_KIND_BUFFER,
    MIXTURE_KIND_REAGENT_MIX,
    MIXTURE_KIND_OTHER,
)


# ── Component roles ────────────────────────────────────────────────────
#
# Every component plays a role inside the mixture. ``solute`` is the
# active ingredient whose concentration matters; ``solvent`` is the
# bulk diluent; ``cosolvent`` is a secondary solvent (hexane:EtOAc
# 95:5 has both as cosolvents); ``additive`` is a minor modifier
# (e.g. 0.1% TFA in HPLC mobile phase) too small to be a primary
# component.

COMPONENT_ROLE_SOLUTE = "solute"
COMPONENT_ROLE_SOLVENT = "solvent"
COMPONENT_ROLE_COSOLVENT = "cosolvent"
COMPONENT_ROLE_ADDITIVE = "additive"

COMPONENT_ROLES = (
    COMPONENT_ROLE_SOLUTE,
    COMPONENT_ROLE_SOLVENT,
    COMPONENT_ROLE_COSOLVENT,
    COMPONENT_ROLE_ADDITIVE,
)


# ── Concentration units ────────────────────────────────────────────────
#
# Stored as a free string because the chemistry literature uses many
# inconsistent forms; these are the canonical ones the UI offers in a
# dropdown but anything else is allowed for edge cases (Stoic doesn't
# convert between units automatically — that responsibility lies
# elsewhere; here we just preserve what the user wrote).

CONCENTRATION_UNITS = (
    "M",  # molarity, mol/L
    "N",  # normality (HCl 1N, H2SO4 0.5N, …)
    "mM",  # millimolarity
    "%v/v",  # volume fraction
    "%w/w",  # mass fraction
    "%w/v",  # mass-volume fraction
    "mg/mL",
    "g/L",
    "ppm",
    "ratio",  # for free ratios like 95:5 — stored as the numerator
)


class Mixture(db.Model):
    """A physical preparation: solution, eluent, buffer, or reagent mix.

    Maps one-to-many onto ``InventoryItem`` (lots): you can have
    multiple lots of "HCl 1N" tracked separately.

    Composition can be:

    * **Empty** — the "quick label" case: name + maybe a primary
      concentration, nothing else. Useful when you need to put a
      bottle in inventory immediately and don't want to fill the
      detailed form. Can be enriched later.
    * **Detailed** — one or more ``MixtureComponent`` rows pointing
      at ``Substance``s with roles and concentrations. The right
      shape for traceable lab work.

    GHS safety overrides (the ``ghs_*_override`` JSON columns) are
    NULL by default, in which case the safety view of the mixture
    derives from the components. Set them to non-null lists to
    override at the mixture level (typically when a dilute solution
    no longer warrants the pure substance's hazard codes).
    """

    __tablename__ = "mixture"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Identification
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=MIXTURE_KIND_SOLUTION,
        index=True,
    )

    # Free-text description for the quick-label use case. The user can
    # type "1N HCl prepared from 12N stock, see notebook p. 47" without
    # filling in the structured fields. Has nothing to do with notes
    # (which is for any extra commentary AFTER the mixture is fully
    # described).
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Primary concentration / unit — for the common case of a single
    # solute at a known concentration ("HCl 1N", "NaOH 0.5 M"). When
    # populated, this is what the label and inventory views display.
    # For multi-component mixtures (eluents) leave NULL and rely on
    # the per-component concentrations instead.
    primary_concentration: Mapped[float | None] = mapped_column(Float, nullable=True)
    primary_concentration_unit: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
    )

    # Optional FK to the principal solvent (water for aqueous
    # solutions, the major solvent for non-aqueous mixtures). Used by
    # the label renderer to show "HCl 1N (aq)" or similar.
    primary_solvent_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("substance.id"),
        nullable=True,
    )

    # GHS overrides — JSON list of pictogram codes / phrase codes.
    # NULL means "derive from components"; a list (even an empty
    # list) means "override". An empty list is meaningful: it
    # explicitly clears the inherited hazards (e.g. "this dilute
    # solution carries no GHS hazard").
    ghs_pictograms_override: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    h_phrases_override: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    p_phrases_override: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    # Owner group — same model as Substance/InventoryItem.
    group_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("group.id"),
        nullable=True,
        index=True,
    )

    # Status / lifecycle
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
    )

    # Free-text notes (post-creation commentary)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Solvent recovery (v1.5.0) ───────────────────────────────
    # A recovered eluent gets a catalogue entry like any other
    # preparation, but one shared by every recovery that rounds to the
    # same composition: fifty columns at 90:10 give one row here and
    # fifty lots. ``recovery_signature`` is that dedup key, built from
    # substance ids and rounded percentages (``rec:12@60|7@40``) so
    # renaming a substance does not fork the catalogue.
    is_recovered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    recovery_signature: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)

    # Audit
    created_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("user.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_now_utc,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_now_utc,
        onupdate=_now_utc,
        nullable=False,
    )

    # Relationships
    # SQLAlchemy needs ``foreign_keys`` here because MixtureComponent
    # has TWO FKs pointing at Mixture: ``mixture_id`` (the parent —
    # this side of the back_populates) and ``child_mixture_id`` (a
    # component that is itself a Mixture). Without disambiguation
    # SQLAlchemy raises AmbiguousForeignKeysError at mapper compile.
    components: Mapped[list[MixtureComponent]] = relationship(
        "MixtureComponent",
        back_populates="mixture",
        foreign_keys="MixtureComponent.mixture_id",
        cascade="all, delete-orphan",
        order_by="MixtureComponent.position",
    )
    primary_solvent: Mapped[Substance | None] = relationship(
        Substance,
        foreign_keys=[primary_solvent_id],
    )
    inventory_items: Mapped[list[InventoryItem]] = relationship(
        "InventoryItem",
        back_populates="mixture",
        primaryjoin="Mixture.id == InventoryItem.mixture_id",
    )

    # ── Derived properties ─────────────────────────────────────────

    @property
    def derived_pictograms(self) -> list[str]:
        """Pictograms derived from components (sorted, deduplicated).

        Union of the pictograms of each constituent. For substance
        components, reads ``Substance.ghs_pictograms`` directly. For
        mixture components, recurses into the child's
        ``effective_pictograms`` so manual overrides are honoured.
        """
        return self._derived_pictograms_recursive(set())

    def _derived_pictograms_recursive(self, visited: set[int]) -> list[str]:
        """Internal: walks the component tree with a cycle guard.

        ``visited`` accumulates Mixture ids already processed. If
        the user somehow builds a loop (A contains B contains A —
        should be prevented by UI but not by the schema), we stop
        rather than recurse forever.
        """
        if self.id is not None and self.id in visited:
            return []
        next_visited = visited | {self.id} if self.id is not None else visited

        seen: set[str] = set()
        out: list[str] = []
        for comp in self.components:
            picts: list[str] = []
            if comp.child_mixture is not None:
                child = comp.child_mixture
                if child.ghs_pictograms_override is not None:
                    picts = list(child.ghs_pictograms_override)
                else:
                    picts = child._derived_pictograms_recursive(next_visited)
            elif comp.substance is not None and comp.substance.ghs_pictograms:
                picts = comp.substance.ghs_pictograms
            for p in picts:
                if p not in seen:
                    seen.add(p)
                    out.append(p)
        return sorted(out)

    @property
    def effective_pictograms(self) -> list[str]:
        """The pictograms actually shown for this mixture.

        Returns the override list when non-NULL (even if empty —
        empty means "explicitly cleared"); otherwise the derived
        union. This is what the inventory view, the label renderer,
        and any safety report should call.
        """
        if self.ghs_pictograms_override is not None:
            return list(self.ghs_pictograms_override)
        return self.derived_pictograms

    @property
    def derived_h_phrases(self) -> list[str]:
        """H-phrases union from components, deduplicated. Recurses
        into child Mixture components."""
        return self._derived_phrases_recursive(set(), kind="h")

    @property
    def effective_h_phrases(self) -> list[str]:
        if self.h_phrases_override is not None:
            return list(self.h_phrases_override)
        return self.derived_h_phrases

    @property
    def derived_p_phrases(self) -> list[str]:
        """P-phrases union from components, deduplicated. Recurses
        into child Mixture components."""
        return self._derived_phrases_recursive(set(), kind="p")

    @property
    def effective_p_phrases(self) -> list[str]:
        if self.p_phrases_override is not None:
            return list(self.p_phrases_override)
        return self.derived_p_phrases

    def _derived_phrases_recursive(
        self,
        visited: set[int],
        *,
        kind: str,
    ) -> list[str]:
        """Internal: shared body for H/P phrase derivation.

        ``kind`` is "h" or "p"; picks which attribute to read on
        Substance and which override to honour on a child Mixture.
        Cycle guard mirrors ``_derived_pictograms_recursive``.
        """
        if self.id is not None and self.id in visited:
            return []
        next_visited = visited | {self.id} if self.id is not None else visited

        sub_attr = "h_phrases" if kind == "h" else "p_phrases"
        override_attr = "h_phrases_override" if kind == "h" else "p_phrases_override"

        seen: set[str] = set()
        out: list[str] = []
        for comp in self.components:
            phrases: list[str] = []
            if comp.child_mixture is not None:
                child = comp.child_mixture
                child_override = getattr(child, override_attr)
                if child_override is not None:
                    phrases = list(child_override)
                else:
                    phrases = child._derived_phrases_recursive(
                        next_visited,
                        kind=kind,
                    )
            elif comp.substance is not None:
                sub_phrases = getattr(comp.substance, sub_attr)
                if sub_phrases:
                    phrases = sub_phrases
            for ph in phrases:
                if ph not in seen:
                    seen.add(ph)
                    out.append(ph)
        return sorted(out)

    @property
    def display_label(self) -> str:
        """Short label suitable for inventory rows and labels.

        Builds "<name> (<conc> <unit>)" when a primary concentration
        is set, falling back to just the name. Doesn't try to
        reproduce the component list — that lives in dedicated views.
        """
        if self.primary_concentration is not None and self.primary_concentration_unit:
            return f"{self.name} ({self.primary_concentration:g} {self.primary_concentration_unit})"
        return self.name

    def __repr__(self) -> str:  # pragma: no cover — debugging only
        return f"<Mixture id={self.id} name={self.name!r} kind={self.kind}>"

    def suggested_expiry_date(self, _visited: set[int] | None = None):
        """Suggested expiry date for a new lot of this mixture.

        Used to pre-fill the "expiry_date" field on the manual-lot
        form and the prepare form. The logic: for each component,
        find the earliest expiry among that component's active
        precursor lots; the mixture's suggested expiry is the
        minimum across components.

        Returns None when no component has any datable lot — in
        that case the form is left blank rather than guessing.

        For mixture-as-component, recurses into the child mixture
        with a visited-set guard (same pattern as ``derived_pictograms``).
        Pulls in here from the recursive helper rather than
        duplicating, since the cycle case is identical.
        """
        from datetime import date as _date

        if _visited is None:
            _visited = set()
        if self.id is not None and self.id in _visited:
            return None
        next_visited = _visited | {self.id} if self.id is not None else _visited

        candidates: list[_date] = []
        for comp in self.components:
            if comp.child_mixture is not None:
                # Recurse — the child's "suggested" expiry is the
                # earliest of ITS components' lots, which is the
                # right thing to propagate.
                sub = comp.child_mixture.suggested_expiry_date(next_visited)
                if sub is not None:
                    candidates.append(sub)
            elif comp.substance is not None:
                # Earliest expiry among the substance's active lots
                # that have one set.
                lot_exps = [
                    lot.expiry_date
                    for lot in comp.substance.inventory_items
                    if lot.is_active and lot.expiry_date is not None
                ]
                if lot_exps:
                    candidates.append(min(lot_exps))
        if not candidates:
            return None
        return min(candidates)


class MixtureComponent(db.Model):
    """One ingredient inside a ``Mixture``.

    Points at EITHER a pure ``Substance`` OR another ``Mixture``
    (the "child mixture", used when one mixture is prepared by
    diluting another — e.g. HCl 6N from HCl 12N stock). Exactly
    one of ``substance_id`` and ``child_mixture_id`` is set per
    row; this is enforced by a CHECK constraint at migration time.

    Records its role (solute/solvent/cosolvent/additive) and
    concentration in the mixture. Concentration units are
    free-form strings — see ``CONCENTRATION_UNITS`` for the
    canonical set the UI offers.

    Position determines display order in the UI (we want HCl listed
    before water when showing "HCl 1N"). It's not a strict ordering
    in any chemical sense; just for UX stability.

    Note on cycles: nothing in the schema prevents
    "mixture A contains mixture B contains mixture A". The
    application-level UI checks (the dropdown filters out the
    current mixture's own id) catch the trivial 1-hop loop.
    Deeper cycles are user error; the ``derived_pictograms`` /
    ``derived_h_phrases`` / ``derived_p_phrases`` properties
    protect against infinite recursion with a visited-set guard.
    """

    __tablename__ = "mixture_component"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    mixture_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("mixture.id"),
        nullable=False,
        index=True,
    )
    # XOR with child_mixture_id: exactly one is set. CHECK
    # constraint is in the Alembic migration since SQLAlchemy
    # CheckConstraint on Mapped columns is awkward to express
    # cleanly without dropping into __table_args__.
    substance_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("substance.id"),
        nullable=True,
        index=True,
    )
    # The "child mixture" — set when this component is itself a
    # mixture (e.g. HCl 12N used as a stock when preparing HCl 6N).
    # Distinct from ``mixture_id`` which is the FK BACK to the
    # owning Mixture (the parent). Named "child" because in the
    # hierarchy the owning mixture is the parent and this is one
    # of its inputs.
    child_mixture_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("mixture.id"),
        nullable=True,
        index=True,
    )

    role: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=COMPONENT_ROLE_SOLUTE,
    )

    concentration: Mapped[float | None] = mapped_column(Float, nullable=True)
    concentration_unit: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
    )

    # Display order within the mixture's component list. Defaults to
    # 0; the form/UI assigns sequential positions when adding rows.
    position: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    mixture: Mapped[Mixture] = relationship(
        Mixture,
        foreign_keys=[mixture_id],
        back_populates="components",
    )
    substance: Mapped[Substance | None] = relationship(
        Substance,
        foreign_keys=[substance_id],
    )
    child_mixture: Mapped[Mixture | None] = relationship(
        "Mixture",
        foreign_keys=[child_mixture_id],
    )

    @property
    def is_mixture_component(self) -> bool:
        """True if this row points at a child Mixture rather than
        a pure Substance. Handy in templates and for the UI which
        renders the two cases slightly differently."""
        return self.child_mixture_id is not None

    @property
    def display_name(self) -> str:
        """Human label for either flavour of component. Used in
        list views, hazard rollups, and the form's read-only
        rendering of existing components."""
        if self.child_mixture is not None:
            return self.child_mixture.display_label
        if self.substance is not None:
            return self.substance.display_name
        return "?"

    def __repr__(self) -> str:  # pragma: no cover
        ref = (
            f"mix={self.child_mixture_id}"
            if self.child_mixture_id is not None
            else f"sub={self.substance_id}"
        )
        return f"<MixtureComponent id={self.id} {ref} role={self.role}>"
