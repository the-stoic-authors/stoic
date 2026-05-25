"""Stoic ELN — Substance forms."""

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


class SubstanceForm(FlaskForm):
    """Create or edit a substance manually."""

    name = StringField(
        _l("Nome"),
        validators=[DataRequired(), Length(max=200)],
        render_kw={"placeholder": "es. DCM, MD541B, Caffeine"},
    )
    iupac_name = StringField(_l("Nome IUPAC"), validators=[Optional(), Length(max=500)])
    cas_number = StringField(
        _l("CAS"),
        validators=[Optional(), Length(max=20)],
        render_kw={"placeholder": "1234-56-7"},
    )
    molecular_formula = StringField(
        _l("Formula"),
        validators=[Optional(), Length(max=100)],
        render_kw={"placeholder": "C8H10N4O2"},
    )
    molecular_weight = FloatField(
        _l("Peso molecolare (g/mol)"),
        validators=[Optional(), NumberRange(min=0)],
    )
    smiles = StringField(_l("SMILES"), validators=[Optional()])
    inchi = StringField(_l("InChI"), validators=[Optional()])
    inchi_key = StringField(
        _l("InChIKey"),
        validators=[Optional(), Length(max=27)],
        render_kw={"placeholder": "AAAAAAAAAAAAAA-BBBBBBBBBB-N"},
    )
    density = FloatField(_l("Densità (g/mL)"), validators=[Optional(), NumberRange(min=0)])
    state = SelectField(
        _l("Stato fisico"),
        choices=[
            ("", "—"),
            ("solid", _l("Solido")),
            ("liquid", _l("Liquido")),
            ("gas", _l("Gas")),
        ],
        validators=[Optional()],
    )
    is_solvent = BooleanField(_l("Solvente (dosato in mL)"))
    melting_point_c = FloatField(_l("Punto di fusione (°C)"), validators=[Optional()])
    boiling_point_c = FloatField(_l("Punto di ebollizione (°C)"), validators=[Optional()])
    notes = TextAreaField(_l("Note"), validators=[Optional()])

    # GHS data — populated dynamically from form data, not validated against fixed choices
    # We use SelectMultipleField rendered as a custom widget in the template.
    ghs_pictograms = SelectMultipleField(
        _l("Pittogrammi GHS"),
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
        _l("Frasi H (separate da virgola)"),
        validators=[Optional()],
        render_kw={"placeholder": "H225, H319, H336"},
    )
    p_phrases_text = StringField(
        _l("Frasi P (separate da virgola)"),
        validators=[Optional()],
        render_kw={"placeholder": "P210, P280, P305"},
    )

    submit = SubmitField(_l("Salva"))


class PubChemImportForm(FlaskForm):
    """Lookup form for PubChem import."""

    query = StringField(
        _l("Cerca"),
        validators=[DataRequired(), Length(max=500)],
        render_kw={
            "placeholder": "Caffeine, 64-17-5, CCO, InChI=1S/...",
            "autofocus": True,
        },
    )
    query_type = SelectField(
        _l("Tipo"),
        choices=[
            ("auto", _l("Rilevamento automatico")),
            ("name", _l("Nome")),
            ("cas", _l("Numero CAS")),
            ("smiles", "SMILES"),
            ("inchi", "InChI"),
            ("inchikey", "InChIKey"),
            ("cid", _l("PubChem CID")),
        ],
        default="auto",
    )
    submit = SubmitField(_l("Cerca su PubChem"))


class PubChemConfirmForm(FlaskForm):
    """Hidden-field-only form to commit PubChem search results."""

    submit = SubmitField(_l("Importa"))
