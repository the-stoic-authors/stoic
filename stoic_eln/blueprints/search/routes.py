"""Routes for the global search / command palette."""

from flask import jsonify, request, url_for
from flask_babel import gettext as _
from flask_login import login_required

from stoic_eln.blueprints.search import bp
from stoic_eln.services import global_search

# Maps an entity type to (translated label, url builder). The url builder
# takes the hit id and returns the detail page. Kept here, in the request
# layer, because url_for needs an app/request context.
_URL_BUILDERS = {
    "substance": lambda i: url_for("substances.detail", substance_id=i),
    "reaction": lambda i: url_for("reactions.detail", reaction_id=i),
    "run": lambda i: url_for("runs.detail", run_id=i),
    "mixture": lambda i: url_for("mixtures.detail", mixture_id=i),
    "inventory": lambda i: url_for("inventory.edit", item_id=i),
    "order": lambda i: url_for("orders.detail", order_id=i),
    "prep": lambda i: url_for("preps.detail", prep_id=i),
    "procedure": lambda i: url_for("procedures.index", _anchor=f"template-{i}"),
}


def _type_label(kind: str) -> str:
    return {
        "substance": _("Sostanza"),
        "reaction": _("Reazione"),
        "run": _("Run"),
        "mixture": _("Miscela"),
        "inventory": _("Inventario"),
        "order": _("Ordine"),
        "prep": _("Preparazione"),
        "procedure": _("Procedura"),
    }.get(kind, kind)


@bp.route("/", methods=["GET"])
@login_required
def query():
    """Return JSON search results for the command palette."""
    q = request.args.get("q", "")
    hits = global_search.search(q)

    for h in hits:
        h["type_label"] = _type_label(h["type"])
        builder = _URL_BUILDERS.get(h["type"])
        h["url"] = builder(h["id"]) if builder else "#"

    return jsonify({"query": q.strip(), "results": hits})
