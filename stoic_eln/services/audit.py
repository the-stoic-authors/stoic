"""Stoic ELN — Audit service.

Provides a single function ``log_event`` for recording user-driven actions.
Used by blueprints and other services to track create/update/delete/login/etc.

Read-event tracking with batch flushing will be added in Week 5.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import has_request_context, request
from flask_login import current_user

from stoic_eln.extensions import db
from stoic_eln.models.audit import AuditLog

logger = logging.getLogger(__name__)


def log_event(
    *,
    action: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    details: dict[str, Any] | None = None,
    user_id: int | None | type = ...,  # sentinel: ... means "auto-detect"
) -> AuditLog | None:
    """Record an audit event.

    Args:
        action: Verb describing what happened (e.g. "create", "login", "delete").
        entity_type: Logical entity type (e.g. "substance", "user").
        entity_id: ID of the affected entity, if applicable.
        details: Optional structured payload (diff, error info, etc.).
        user_id: User responsible for the action. If left as the sentinel
            (the default), it is auto-detected from ``current_user``. Pass
            ``None`` explicitly for system events.

    Returns:
        The created AuditLog row, or None if logging failed (logged but not raised).
    """
    try:
        if user_id is ...:
            user_id = (
                current_user.id
                if (has_request_context() and current_user.is_authenticated)
                else None
            )

        ip = None
        if has_request_context():
            # Honour proxy headers if present
            ip = request.headers.get("X-Forwarded-For", request.remote_addr)
            if ip and "," in ip:
                ip = ip.split(",")[0].strip()

        event = AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
            ip_address=ip,
        )
        db.session.add(event)
        db.session.commit()
        return event
    except Exception:
        # Never let audit failure break the user request
        logger.exception("Failed to log audit event: action=%s entity=%s", action, entity_type)
        db.session.rollback()
        return None
