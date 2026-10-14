"""Audit trail. ponytail: a single insert helper, no events framework.

`user_id` is the acting user's email and is passed explicitly by every caller.
It was optional and universally omitted, so an audit trail on a log-extraction
platform recorded what happened and never who did it.

Passed rather than picked up from request context on purpose: a ContextVar set
inside a sync dependency never reaches the endpoint (FastAPI runs those in a
threadpool, and the copy does not flow back), which fails silently — the rows
just keep saying None.

The caller's session is reused; the row is flushed with the surrounding commit.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AuditLog


def record(
    db: Session,
    action: str,
    entity: str,
    entity_id: int | None = None,
    metadata: dict | None = None,
    user_id: str | None = None,
) -> None:
    db.add(
        AuditLog(action=action, entity=entity, entity_id=entity_id, meta=metadata, user_id=user_id)
    )
