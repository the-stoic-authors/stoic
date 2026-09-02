"""HTMX requests must carry a CSRF token.

Why this file exists (v1.5.3)
-----------------------------
Assigning a lot to a *step* component silently did nothing in real
use, while 764 tests stayed green. Two things lined up:

* ``TestingConfig`` disables CSRF, so the whole suite was blind to it;
* the step controls in ``runs/detail.html`` posted with bare
  ``hx-post`` attributes, outside any ``<form>``, so no token was
  ever sent. The main-component controls happened to sit inside a
  ``<form>`` carrying a hidden token, which is why *those* worked.

Flask-WTF rejected the step posts with 400. With ``hx-swap="none"``
the browser showed nothing at all, the dropdown kept displaying the
lot the user had picked, and the assignment looked like it had
worked. It had not — which in turn made v1.4.4's inventory deduction
look broken, because a component with no lot has nothing to deduct.

The fix puts the token on ``<body>`` in ``base.html`` via
``hx-headers``, so every HTMX request in the app inherits it.

These tests turn CSRF back on for the app under test, which is the
only way to see any of this.
"""

from __future__ import annotations

import re

import pytest

from stoic_eln.extensions import db
from stoic_eln.models.run_step import RunStepComponent

# Imported without a package prefix on purpose: ``tests/`` has no
# __init__.py, so pytest puts that directory on sys.path directly.
# ``from tests.… import`` resolves only where the project root also
# happens to be importable, which is not the case on a plain checkout.
from test_step_inventory_deduction import (  # noqa: F401
    operator,
    run_with_step,
)

TOKEN_RE = re.compile(r'hx-headers=\'{"X-CSRFToken": "([^"]+)"}\'')


@pytest.fixture()
def csrf_client(app, operator, run_with_step):  # noqa: F811
    """A logged-in client against an app with CSRF *enabled*."""
    app.config["WTF_CSRF_ENABLED"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(operator)
        sess["_fresh"] = True
    return client


def test_body_exposes_the_csrf_token_to_htmx(csrf_client, run_with_step):  # noqa: F811
    """Every page must hand HTMX a token, or bare hx-post is dead."""
    page = csrf_client.get(f"/runs/{run_with_step['run']}")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert TOKEN_RE.search(html), "no hx-headers token on <body>"


def test_step_lot_post_without_token_is_rejected(csrf_client, run_with_step):  # noqa: F811
    """The failure mode that fooled us: rejected, and quietly."""
    scid = run_with_step["step_component"]
    res = csrf_client.post(
        f"/runs/{run_with_step['run']}/step_component/{scid}/lot",
        data={"lot_id": str(run_with_step["lot_a"])},
        headers={"HX-Request": "true"},
    )
    assert res.status_code == 400


def test_step_lot_post_with_the_page_token_persists(app, csrf_client, run_with_step):  # noqa: F811
    """The browser's real path: read the token, send it, lot sticks."""
    run_id = run_with_step["run"]
    scid = run_with_step["step_component"]

    html = csrf_client.get(f"/runs/{run_id}").get_data(as_text=True)
    token = TOKEN_RE.search(html).group(1)

    res = csrf_client.post(
        f"/runs/{run_id}/step_component/{scid}/lot",
        data={"lot_id": str(run_with_step["lot_a"])},
        headers={"HX-Request": "true", "X-CSRFToken": token},
    )
    assert res.status_code in (200, 204)

    with app.app_context():
        sc = db.session.get(RunStepComponent, scid)
        assert sc.inventory_item_id == run_with_step["lot_a"]
