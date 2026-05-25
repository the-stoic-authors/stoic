"""Stoic ELN — Reaction model (template).

A Reaction is a re-usable "recipe": it captures the chemistry, the components,
the procedure, and the conditions. Each concrete execution is a Run (Week 4).

A reaction has many components (ReactionComponent), which link to substances
with a role (starting_material, reagent, catalyst, solvent, product, ...).
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import TYPE_CHECKING

from sqlalchemy import (
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

if TYPE_CHECKING:
    from stoic_eln.models.checklist_item import ChecklistItem
    from stoic_eln.models.reaction_component import ReactionComponent
    from stoic_eln.models.reaction_step import ReactionStep
    from stoic_eln.models.run import Run
    from stoic_eln.models.user import User


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Reaction(db.Model):
    """A reaction template — the chemistry recipe, not a specific execution."""

    __tablename__ = "reaction"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # User-chosen mnemonic code (e.g. "SUZ", "BUCH-A", "TEM1"). Used as a
    # building block for run codes. Uniqueness is enforced at application
    # level (only one *published* reaction can hold a given template_code,
    # but a draft can hold the same code as its parent published version).
    template_code: Mapped[str | None] = mapped_column(
        String(20), index=True, nullable=True,
    )
    """Mnemonic identifier the chemist picks. NULL while the template is
    still in 'draft' status before the first save."""

    # Internal sequential code (kept for backwards compatibility and as a
    # fallback display when template_code is empty). Format: 'RX-YYYY-NNNN'.
    code: Mapped[str] = mapped_column(
        String(20), unique=True, index=True, nullable=False
    )
    """Auto-generated identifier like 'RX-2026-0001'.

    Note: with the new system the user-facing ID is the template_code; this
    column is kept as an internal stable id (also useful for legacy data).
    """

    # Lifecycle status — drafts hold WIP edits and are filtered out of
    # most listings unless the user is the draft's author.
    status: Mapped[str] = mapped_column(
        String(16), default="published", nullable=False, index=True,
    )
    """One of 'draft', 'published'."""

    # Set on a draft when it was created via clone_for_editing of an existing
    # published reaction. Used by promote_draft to know which published row
    # this draft is intended to replace, even if its template_code has been
    # edited to a different value during the editing session.
    parent_published_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("reaction.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Versioning. The "template_code" above includes the version suffix
    # (e.g. "MD600B.2"); "template_code_base" stores the family root the
    # operator types in (e.g. "MD600B"). All versions of a family share
    # the same base code; their version_number differs (1, 2, 3, ...).
    # ``parent_version_id`` links a version N to its predecessor (version
    # N-1); for the very first version this is NULL.
    # Archived versions are hidden from the main reactions list but remain
    # in the DB so historical Runs continue to point at the exact template
    # they were executed against.
    template_code_base: Mapped[str | None] = mapped_column(
        String(20), index=True, nullable=True,
    )
    """The "family" code without version suffix (e.g. 'MD600B').
    Same for every version of the same template family."""

    version_number: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False, index=True,
    )
    """1 for the first version, 2 for the second, …"""

    parent_version_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("reaction.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    """FK to the previous version of the same family (NULL for v1)."""

    is_archived: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True,
    )
    """True for old versions (v1 once v2 exists, etc.). Filtered out of
    the main listing but accessible via 'Versioni precedenti'."""

    title: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Free-form scientific rationale or scope."""

    procedure: Mapped[str | None] = mapped_column(Text, nullable=True)
    """The general protocol — markdown-friendly free text."""

    # Conditions
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    atmosphere: Mapped[str | None] = mapped_column(String(40), nullable=True)
    """e.g. 'air', 'N2', 'Ar', 'vacuum'."""

    pressure_bar: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Reaction scheme as SMILES (used for SmilesDrawer rendering)
    # Format: 'reactants>>products' or 'reactants>reagents>products'
    scheme_smiles: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Optional override: if not set, derived from components on render."""

    # Source / reference
    source: Mapped[str | None] = mapped_column(String(500), nullable=True)
    """DOI, internal SOP code, paper citation, free text."""

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Default scale used to preview absolute quantities in the template view.
    # Equivalents are the canonical stoichiometry; this is just a display hint.
    # When a Run is created (Week 4), it gets its own scale_mmol that overrides.
    default_scale_mmol: Mapped[float] = mapped_column(
        Float, default=1.0, nullable=False
    )

    # Audit
    created_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("user.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now_utc, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now_utc, onupdate=_now_utc, nullable=False
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )

    # Relationships
    created_by: Mapped[User | None] = relationship(
        "User", foreign_keys=[created_by_id]
    )
    components: Mapped[list[ReactionComponent]] = relationship(
        "ReactionComponent",
        back_populates="reaction",
        cascade="all, delete-orphan",
        order_by="ReactionComponent.position.asc()",
    )
    checklist_items: Mapped[list[ChecklistItem]] = relationship(
        "ChecklistItem",
        primaryjoin=(
            "and_(ChecklistItem.reaction_id == Reaction.id, "
            "ChecklistItem.step_id.is_(None))"
        ),
        cascade="all, delete-orphan",
        order_by="ChecklistItem.position.asc()",
        overlaps="step",  # silence the warning about ChecklistItem.reaction_id usage
    )
    steps: Mapped[list[ReactionStep]] = relationship(
        "ReactionStep",
        back_populates="reaction",
        cascade="all, delete-orphan",
        order_by="ReactionStep.position.asc()",
    )
    runs: Mapped[list[Run]] = relationship(
        "Run",
        back_populates="reaction",
        order_by="Run.created_at.desc()",
        # Runs are immutable historical records and outlive their templates.
        # We tell SQLAlchemy NOT to touch them when the parent is deleted
        # (passive_deletes=True means leave the FK alone, let the DB handle
        # it via ON DELETE — but since reaction_id is NOT NULL, we should
        # prevent template deletion when runs reference it). In practice,
        # we never delete published templates: ``promote_draft`` now updates
        # in place instead of replacing.
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Reaction {self.code} {self.title!r}>"

    @property
    def display_name(self) -> str:
        return f"{self.display_code} — {self.title}"

    @property
    def display_code(self) -> str:
        """Prefer the user-chosen template_code; fall back to the internal
        sequential code if not set (legacy data, drafts still being filled in).
        """
        if self.is_draft:
            return self.draft_display_code
        return self.template_code or self.code

    @property
    def draft_display_code(self) -> str:
        """Show the future versioned code for a draft.

        - A draft with a parent_published_id (clone for editing) →
          ``<base>.<next_version>`` (e.g. 'MD600B.2' if editing v1).
        - A new-from-scratch draft with a base set → ``<base>`` only
          (no version yet — the user can still change it).
        - Empty draft (no base typed yet) → '—'.
        """
        if not self.template_code_base:
            return "—"
        if self.parent_published_id:
            # Editing a parent published version → next version number
            from stoic_eln.extensions import db
            parent = db.session.get(Reaction, self.parent_published_id)
            next_v = (parent.version_number + 1) if parent else 2
            return f"{self.template_code_base}.{next_v}"
        # Brand-new draft, will become .1
        return f"{self.template_code_base}.1"

    @property
    def is_draft(self) -> bool:
        return self.status == "draft"

    # ─── Component partitioning helpers ───────────────────────────────────────
    @property
    def starting_materials(self) -> list[ReactionComponent]:
        return [c for c in self.components if c.role == "starting_material"]

    @property
    def reactants(self) -> list[ReactionComponent]:
        return [c for c in self.components if c.role == "reactant"]

    @property
    def reagents(self) -> list[ReactionComponent]:
        return [
            c
            for c in self.components
            if c.role
            in (
                "reagent",
                "catalyst",
                "ligand",
                "base",
                "acid",
                "oxidant",
                "reductant",
                "additive",
            )
        ]

    @property
    def solvents(self) -> list[ReactionComponent]:
        return [c for c in self.components if c.role == "solvent"]

    @property
    def products(self) -> list[ReactionComponent]:
        return [c for c in self.components if c.role == "product"]

    @property
    def byproducts(self) -> list[ReactionComponent]:
        return [c for c in self.components if c.role == "byproduct"]

    @property
    def limiting_component(self) -> ReactionComponent | None:
        """The component flagged as is_limiting; falls back to first SM."""
        for c in self.components:
            if c.is_limiting:
                return c
        sms = self.starting_materials
        return sms[0] if sms else None

    def derive_scheme_smiles(self) -> str:
        """Build a 'A.B>C>D.E' SMILES from component substances + roles.

        Backwards-compatible string getter. Used by tests; new code should
        prefer ``derive_scheme()`` which returns structured data.
        """
        if self.scheme_smiles:
            return self.scheme_smiles
        scheme = self.derive_scheme()
        return scheme["smiles"] if scheme else ""

    def derive_scheme(self) -> dict | None:
        """Build a structured scheme description from components + conditions.

        Returns a dict with these keys (all optional except 'smiles'):

          - smiles: str — the SMILES string with reactants>agents>products
                    syntax. Only includes substances that HAVE a SMILES.
                    Empty string if nothing renderable.
          - left:   list[dict] — substances on the LEFT of the arrow
                    (starting_material + reactant). Each dict has 'name',
                    'smiles' (may be None), 'role'.
          - agents: list[dict] — substances ABOVE the arrow
                    (reagent, catalyst, ligand, base, acid, oxidant,
                    reductant, additive).
          - right:  list[dict] — substances on the RIGHT of the arrow
                    (product, byproduct).
          - solvents: list[dict] — substances BELOW the arrow (solvent role),
                    each with 'name' and optional 'concentration_M'.
          - conditions: str — formatted condition line for under the arrow.
                    Combines temp, duration, atmosphere, pressure that are set.

        Returns None if there are no left-side reactants AND no right-side
        products (truly empty reaction — nothing to render).

        If ``self.scheme_smiles`` is set (manual override), the function
        still returns the structured form so the template can render
        solvents+conditions below the arrow, but the SMILES will be the
        manual one instead of derived.
        """
        # Empty reaction — nothing to draw
        if not self.components:
            return None

        # Role buckets:
        #   - left_only_roles: always go LEFT regardless of stoichiometry
        #   - right_only_roles: always go RIGHT
        #   - over_arrow_roles: catalysts, bases, etc. — always go OVER the arrow
        #     (they're not "co-reactants" in the chemical sense, and are
        #     typically sub-stoichiometric)
        #   - reagent_role: "reagent" is a true co-reactant and ALWAYS
        #     goes LEFT, regardless of equivalents. Even with 4 eq
        #     excess of e.g. an amine nucleophile, it's still consumed
        #     stoichiometrically (just in excess) and chemically belongs
        #     with the substrate, not above the arrow.
        left_only_roles = ("starting_material", "reactant")
        right_only_roles = ("product", "byproduct")
        over_arrow_roles = ("catalyst", "ligand", "base", "acid",
                            "oxidant", "reductant", "additive")

        def comp_dict(c) -> dict:
            sub = c.substance
            return {
                "name": sub.name if sub else "?",
                "smiles": (sub.smiles if sub and sub.smiles else None),
                "molecular_formula": (sub.molecular_formula if sub else None),
                "role": c.role,
                "is_limiting": c.is_limiting,
                "equivalents": c.equivalents,
            }

        left: list[dict] = []
        # agents_drawn was for "reagent" with large excess shown over the
        # arrow, but that turned out to be wrong chemistry — reagents
        # always belong with the substrate on the left. The list is kept
        # so callers that expected it don't break; it's just always empty.
        # agents_text  = "true" catalysts / bases / acids / oxidants /
        # reductants / ligands / additives — these go ABOVE the arrow as
        # molecular-formula text in SciFinder/Reaxys style (more compact
        # and easier to read for sub-stoichiometric species).
        agents_drawn: list[dict] = []
        agents_text: list[dict] = []
        right: list[dict] = []
        solvents: list[dict] = []

        # All true reagents (role="reagent") go LEFT regardless of
        # equivalents — even with 4 eq excess they're still co-reactants
        # in the chemical sense, not catalysts.
        # The only over-the-arrow species are the explicit role-based
        # ones (catalyst/base/ligand/etc.) which render as text labels.

        for c in self.components:
            d = comp_dict(c)
            if c.role in left_only_roles:
                left.append(d)
            elif c.role in right_only_roles:
                right.append(d)
            elif c.role in over_arrow_roles:
                # Catalysts, bases, ligands etc. → text above arrow
                agents_text.append(d)
            elif c.role == "reagent":
                # Reagents are true co-reactants → always LEFT,
                # drawn as structures alongside the limiting substrate.
                # Equivalents are just a stoichiometry detail, not
                # a positioning signal.
                left.append(d)
            elif c.role == "solvent":
                solvents.append({
                    "name": d["name"],
                    "smiles": d["smiles"],
                    "molecular_formula": d["molecular_formula"],
                    "concentration_M": c.concentration_M,
                })
            elif c.role == "internal_standard":
                # Internal standard never appears in scheme
                continue
            # Unknown roles: ignored

        if not left and not right:
            return None

        # Build the SMILES string for SmilesDrawer.
        # Skip components without SMILES (they render as name placeholders
        # in the template, separate from the canvas).
        def smiles_join(items: list[dict]) -> str:
            return ".".join(i["smiles"] for i in items if i["smiles"])

        left_smi = smiles_join(left)
        agent_smi = smiles_join(agents_drawn)
        right_smi = smiles_join(right)

        # SmilesDrawer can render only if both sides have at least one
        # renderable molecule.
        canvas_safe = bool(left_smi and right_smi)

        if self.scheme_smiles:
            smiles = self.scheme_smiles
            canvas_safe = True  # trust the user's manual SMILES
        elif canvas_safe:
            if agent_smi:
                smiles = f"{left_smi}>{agent_smi}>{right_smi}"
            else:
                smiles = f"{left_smi}>>{right_smi}"
        else:
            smiles = ""

        # Build the condition line. Only pieces that are set.
        cond_parts: list[str] = []
        if self.temperature_c is not None:
            cond_parts.append(f"{self.temperature_c:g} °C")
        if self.duration_hours is not None:
            cond_parts.append(f"{self.duration_hours:g} h")
        if self.atmosphere:
            atm_label = {
                "air": "aria", "N2": "N₂", "Ar": "Ar",
                "vacuum": "vuoto", "H2": "H₂", "O2": "O₂",
            }.get(self.atmosphere, self.atmosphere)
            cond_parts.append(atm_label)
        if self.pressure_bar is not None:
            cond_parts.append(f"{self.pressure_bar:g} bar")
        conditions = " · ".join(cond_parts)

        # Build a textual label for what goes above the arrow:
        # molecular formulas of the TEXT agents only (catalysts, bases,
        # etc.). The drawn agents (reagents) appear as structures above
        # the arrow via the SMILES string itself, not as text.
        # We prefer the stored molecular_formula; if missing, fall back
        # to the substance name. Numbers in molecular formulas are
        # converted to subscript Unicode chars for readability.
        def to_subscript(s: str | None) -> str:
            if not s:
                return ""
            sub_map = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
            return s.translate(sub_map)

        # Normalize transition-metal halide formulas to chemist-readable
        # ordering: RDKit/PubChem may give Br2Cu (Hill order); chemists
        # write CuBr2. Apply a small set of obvious metal-first rewrites.
        def chemist_order(formula: str) -> str:
            """Reorder a molecular formula so the metal comes first."""
            if not formula:
                return formula
            # Match patterns like "Br2Cu", "Cl3Fe", "I2Zn" → "CuBr2" etc.
            import re as _re
            m = _re.match(
                r"^([A-Z][a-z]?)(\d*)([A-Z][a-z]?)(\d*)$",
                formula,
            )
            if not m:
                return formula
            sym1, n1, sym2, n2 = m.groups()
            # Metals that should come first (common ones in synthesis).
            METALS_FIRST = {
                "Li", "Na", "K", "Mg", "Ca", "Mn", "Fe", "Co", "Ni",
                "Cu", "Zn", "Pd", "Pt", "Au", "Ag", "Ru", "Rh", "Ir",
                "Hg", "Sn", "Al", "Ti", "Zr", "V", "Cr", "Cd", "Pb",
            }
            if sym2 in METALS_FIRST and sym1 not in METALS_FIRST:
                # Swap: halide-metal → metal-halide
                return f"{sym2}{n2}{sym1}{n1}"
            return formula

        agent_labels: list[str] = []
        for a in agents_text:
            if a["molecular_formula"]:
                agent_labels.append(
                    to_subscript(chemist_order(a["molecular_formula"]))
                )
            else:
                agent_labels.append(a["name"])
        above_arrow_label = ", ".join(agent_labels)

        return {
            "smiles": smiles,
            "canvas_safe": canvas_safe,
            "left": left,
            # Keep 'agents' key for backwards compat with the template
            # (it merges both drawn and text agents for the "no-SMILES"
            # fallback rendering at the bottom of the scheme card).
            "agents": agents_drawn + agents_text,
            "agents_drawn": agents_drawn,
            "agents_text": agents_text,
            "right": right,
            "solvents": solvents,
            "conditions": conditions,
            "above_arrow_label": above_arrow_label,
        }
