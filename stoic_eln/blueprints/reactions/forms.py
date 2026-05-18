"""Stoic ELN — Reaction forms."""

from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    FloatField,
    HiddenField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional

ROLE_CHOICES = [
    ("starting_material", _l("Materiale di partenza (SM)")),
    ("reactant", _l("Reattivo")),
    ("reagent", _l("Reagente")),
    ("catalyst", _l("Catalizzatore")),
    ("ligand", _l("Legante")),
    ("base", _l("Base")),
    ("acid", _l("Acido")),
    ("oxidant", _l("Ossidante")),
    ("reductant", _l("Riducente")),
    ("solvent", _l("Solvente")),
    ("additive", _l("Additivo")),
    ("internal_standard", _l("Standard interno")),
    ("product", _l("Prodotto")),
    ("byproduct", _l("Sottoprodotto")),
]


class ReactionForm(FlaskForm):
    """Create or edit reaction metadata (the components are managed separately)."""

    title = StringField(
        _l("Titolo"),
        validators=[DataRequired(), Length(max=200)],
        render_kw={"placeholder": "es. Suzuki coupling on aryl bromide"},
    )
    description = TextAreaField(
        _l("Descrizione / razionale"),
        validators=[Optional()],
        render_kw={"rows": 3},
    )
    procedure = TextAreaField(
        _l("Procedura"),
        validators=[Optional()],
        render_kw={"rows": 8, "placeholder": "Markdown supportato."},
    )

    # Conditions
    temperature_c = FloatField(
        _l("Temperatura (°C)"), validators=[Optional()]
    )
    duration_hours = FloatField(
        _l("Durata (h)"), validators=[Optional(), NumberRange(min=0)]
    )
    atmosphere = SelectField(
        _l("Atmosfera"),
        choices=[
            ("", "—"),
            ("air", _l("aria")),
            ("N2", "N₂"),
            ("Ar", "Ar"),
            ("vacuum", _l("vuoto")),
            ("H2", "H₂"),
            ("O2", "O₂"),
        ],
        validators=[Optional()],
    )
    pressure_bar = FloatField(
        _l("Pressione (bar)"), validators=[Optional(), NumberRange(min=0)]
    )

    # Scheme override
    scheme_smiles = StringField(
        _l("Schema SMILES (opzionale)"),
        validators=[Optional(), Length(max=2000)],
        render_kw={
            "placeholder": "CCO.CC(=O)Cl>>CCOC(=O)C",
            "class": "font-monospace",
        },
    )

    source = StringField(
        _l("Fonte / riferimento"),
        validators=[Optional(), Length(max=500)],
        render_kw={"placeholder": "DOI, paper, SOP interno…"},
    )
    notes = TextAreaField(
        _l("Note"), validators=[Optional()], render_kw={"rows": 2}
    )

    submit = SubmitField(_l("Salva"))


class ReactionComponentForm(FlaskForm):
    """Add or edit a single reaction component (used in the inline editor).

    Either ``substance_id`` or ``mixture_id`` is provided (XOR). The
    UI picker emits whichever the user chose; the route validates
    the XOR contract before persisting.
    """

    substance_id = IntegerField(
        _l("Sostanza"), validators=[Optional(), NumberRange(min=1)]
    )
    mixture_id = IntegerField(
        _l("Miscela"), validators=[Optional(), NumberRange(min=1)]
    )
    role = SelectField(
        _l("Ruolo"),
        choices=ROLE_CHOICES,
        validators=[DataRequired()],
        default="reactant",
    )
    equivalents = FloatField(
        _l("Equivalenti"),
        validators=[Optional(), NumberRange(min=0)],
    )
    amount_mmol = FloatField(
        _l("mmol"), validators=[Optional(), NumberRange(min=0)]
    )
    amount_g = FloatField(
        _l("g"), validators=[Optional(), NumberRange(min=0)]
    )
    amount_mL = FloatField(
        _l("mL"), validators=[Optional(), NumberRange(min=0)]
    )
    is_limiting = BooleanField(_l("Reagente limitante"))
    concentration_M = FloatField(
        _l("Concentrazione (M)"),
        validators=[Optional(), NumberRange(min=0)],
    )
    notes = StringField(_l("Note"), validators=[Optional(), Length(max=500)])

    submit = SubmitField(_l("Aggiungi"))
