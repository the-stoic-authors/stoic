"""Stoic ELN — Authentication forms."""

from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, EqualTo, Length


class LoginForm(FlaskForm):
    username = StringField(_l("Username"), validators=[DataRequired(), Length(max=64)])
    password = PasswordField(_l("Password"), validators=[DataRequired()])
    remember_me = BooleanField(_l("Ricordami"))
    submit = SubmitField(_l("Accedi"))


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField(_l("Password attuale"), validators=[DataRequired()])
    new_password = PasswordField(
        _l("Nuova password"),
        validators=[
            DataRequired(),
            Length(min=8, message=_l("La password deve essere lunga almeno 8 caratteri.")),
        ],
    )
    confirm_password = PasswordField(
        _l("Conferma nuova password"),
        validators=[
            DataRequired(),
            EqualTo("new_password", message=_l("Le password non coincidono.")),
        ],
    )
    submit = SubmitField(_l("Cambia password"))
