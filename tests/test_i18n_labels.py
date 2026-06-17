"""Regression tests for translatable enum labels (status / audit action).

These labels became lazy_gettext proxies; evaluating them outside a request
(PDF / background generation) used to crash because the locale selector
dereferenced an unbound current_user. The selector now falls back to the
default locale outside a request context.
"""

from __future__ import annotations

from stoic_eln.models.run import STATUS_COMPLETED, STATUS_DRAFT, Run
from stoic_eln.services.audit_query import label_for_action


def test_run_status_label_str_outside_request(app):
    """str() of a status label must not crash without a request context."""
    with app.app_context():
        r = Run(code="X", year=2026, sequence=1, reaction_id=1, status=STATUS_DRAFT)
        # No request context here — this used to raise AttributeError.
        assert str(r.status_label)  # non-empty
        r.status = STATUS_COMPLETED
        assert str(r.status_label)


def test_audit_action_label_str_outside_request(app):
    with app.app_context():
        label, color = label_for_action("run_complete")
        assert str(label)  # evaluates without a request
        assert color == "success"
        # unknown action falls back to a humanized form
        lbl2, col2 = label_for_action("some_unknown_action")
        assert str(lbl2) == "some unknown action"
        assert col2 == "secondary"
