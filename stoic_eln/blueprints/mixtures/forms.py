"""Stoic ELN — Mixture forms.

The component rows (substance + role + concentration) are handled
dynamically in the route from ``request.form`` rather than a WTForms
``FieldList`` — adding and removing rows interactively is cleaner
that way and the validation rules per-row are simple enough to do by
hand.
"""

from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    FloatField,
    SelectField,
    SelectMultipleField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from stoic_eln.models.mixture import (
    CONCENTRATION_UNITS,
    MIXTURE_KIND_BUFFER,
    MIXTURE_KIND_ELUENT,
    MIXTURE_KIND_OTHER,
    MIXTURE_KIND_REAGENT_MIX,
    MIXTURE_KIND_SOLUTION,
)


# Choices for the kind dropdown — labels in Italian to match the
# rest of the UI.
_KIND_CHOICES: list[tuple[str, str]] = [
    (MIXTURE_KIND_SOLUTION, _l("Soluzione")),
    (MIXTURE_KIND_ELUENT, _l("Eluente")),
    (MIXTURE_KIND_BUFFER, _l("Tampone")),
    (MIXTURE_KIND_REAGENT_MIX, _l("Miscela reagenti")),
    (MIXTURE_KIND_OTHER, _l("Altro")),
]


# Concentration unit dropdown — keep blank as the first option so
# the field is genuinely optional. Unit codes are the canonical set
# from models/mixture.py; users can also type free-form strings if
# they need something exotic (the model doesn't validate against a
# fixed list — see the model docstring).
_CONC_UNIT_CHOICES: list[tuple[str, str]] = (
    [("", "—")]
    + [(u, u) for u in CONCENTRATION_UNITS]
)


class MixtureForm(FlaskForm):
    """Create or edit a mixture (without its components — see notes).

    Component rows (substance + role + concentration) are handled in
    the route by reading ``request.form`` arrays directly. The form
    only covers the top-level fields. This keeps the WTForms layer
    simple and lets the template manage add/remove of rows via JS.
    """

    name = StringField(
        _l("Nome"),
        validators=[DataRequired(), Length(max=200)],
        render_kw={"placeholder": "HCl 1N, Eluente A 95:5, Buffer pH 7.4..."},
    )

    kind = SelectField(
        _l("Tipo"),
        choices=_KIND_CHOICES,
        default=MIXTURE_KIND_SOLUTION,
        validators=[DataRequired()],
    )

    description = TextAreaField(
        _l("Descrizione"),
        validators=[Optional()],
        render_kw={
            "rows": 2,
            "placeholder": (
                "es. 'Diluito 1:5 da stock Sigma 5N, vedi quaderno p.47'. "
                "Lascia vuoto se hai compilato i componenti qui sotto."
            ),
        },
    )

    # Primary concentration — for "X 1N" style soluble-in-bulk-solvent
    # mixtures. Optional: eluents and buffers usually leave blank and
    # rely on per-component concentrations.
    primary_concentration = FloatField(
        _l("Concentrazione principale"),
        validators=[Optional(), NumberRange(min=0)],
        render_kw={"placeholder": "1.0", "step": "any"},
    )
    primary_concentration_unit = SelectField(
        _l("Unità"),
        choices=_CONC_UNIT_CHOICES,
        default="",
        validators=[Optional()],
    )

    # Primary solvent — populated as a hidden field in the template;
    # the picker UI shows only Substance.is_solvent=True candidates.
    # Coerce to int|None at parse time in the route.
    primary_solvent_id = StringField(
        _l("Solvente principale"),
        validators=[Optional()],
    )

    # GHS overrides — same layout as SubstanceForm. The template
    # initialises these from the current effective_* view; if the
    # user changes them, they become the explicit override.
    ghs_pictograms = SelectMultipleField(
        _l("Pittogrammi GHS (override)"),
        choices=[
            ("GHS01", "GHS01 — Esplosivo"),
            ("GHS02", "GHS02 — Infiammabile"),
            ("GHS03", "GHS03 — Comburente"),
            ("GHS04", "GHS04 — Gas sotto pressione"),
            ("GHS05", "GHS05 — Corrosivo"),
            ("GHS06", "GHS06 — Tossicità acuta"),
            ("GHS07", "GHS07 — Irritante"),
            ("GHS08", "GHS08 — Pericolo per la salute"),
            ("GHS09", "GHS09 — Pericolo ambientale"),
        ],
        validators=[Optional()],
    )

    h_phrases_text = StringField(
        _l("Frasi H (override, separate da virgola)"),
        validators=[Optional()],
        render_kw={"placeholder": "H225, H319, H336"},
    )
    p_phrases_text = StringField(
        _l("Frasi P (override, separate da virgola)"),
        validators=[Optional()],
        render_kw={"placeholder": "P210, P280, P305"},
    )

    # Toggle: tells the route whether the override fields should be
    # taken as authoritative or whether to keep them as NULL (so the
    # mixture's effective hazards derive from components).
    use_ghs_override = BooleanField(
        _l("Sovrascrivi GHS dei componenti"),
    )

    notes = TextAreaField(_l("Note"), validators=[Optional()])

    submit = SubmitField(_l("Salva"))
