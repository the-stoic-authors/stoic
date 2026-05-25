"""Stoic ELN — Inventory forms."""

from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateField,
    FloatField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import Length, NumberRange, Optional


class InventoryItemForm(FlaskForm):
    """Add or edit an inventory lot."""

    batch_code = StringField(
        _l("Codice lotto"),
        validators=[Optional(), Length(max=64)],
        render_kw={"placeholder": "es. STBG3140"},
    )
    supplier = StringField(_l("Fornitore"), validators=[Optional(), Length(max=120)])
    catalogue_number = StringField(_l("Codice catalogo"), validators=[Optional(), Length(max=64)])

    initial_quantity_g = FloatField(
        _l("Quantità iniziale (g)"),
        validators=[Optional(), NumberRange(min=0)],
    )
    initial_quantity_mL = FloatField(
        _l("Quantità iniziale (mL)"),
        validators=[Optional(), NumberRange(min=0)],
    )
    quantity_g = FloatField(
        _l("Quantità residua (g)"),
        validators=[Optional(), NumberRange(min=0)],
    )
    quantity_mL = FloatField(
        _l("Quantità residua (mL)"),
        validators=[Optional(), NumberRange(min=0)],
    )

    total_cost_eur = FloatField(
        _l("Costo totale (EUR)"),
        validators=[Optional(), NumberRange(min=0)],
    )
    purchased_at = DateField(_l("Data di acquisto"), validators=[Optional()])
    expiry_date = DateField(_l("Data di scadenza"), validators=[Optional()])
    location = StringField(
        _l("Posizione"),
        validators=[Optional(), Length(max=200)],
        render_kw={"placeholder": "es. Armadio 3, ripiano alto"},
    )
    is_active = BooleanField(_l("Lotto attivo"), default=True)
    notes = TextAreaField(_l("Note"), validators=[Optional()])

    submit = SubmitField(_l("Salva"))
