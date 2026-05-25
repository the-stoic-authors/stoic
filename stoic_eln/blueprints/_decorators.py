"""Shared decorators for role-based access control."""

from __future__ import annotations

from functools import wraps

from flask import abort
from flask_login import current_user


def admin_required(view):
    """Allow only authenticated admins (User.role == 'admin' or is_admin=True)."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if not current_user.can_manage_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapper


def supervisor_required(view):
    """Allow authenticated supervisors AND admins.

    Supervisors and admins are the two roles that can create/edit/delete
    reaction templates and substances. Regular users can only read.
    """

    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if not current_user.can_edit_reactions:
            abort(403)
        return view(*args, **kwargs)

    return wrapper
