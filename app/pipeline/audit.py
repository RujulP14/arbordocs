import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLogEntry


async def log_event(
    db: AsyncSession,
    project_id: uuid.UUID,
    event_type: str,
    subject_type: str,
    subject_id: uuid.UUID,
    actor: str = "system",
    payload: dict | None = None,
) -> AuditLogEntry:
    """Append one entry to the audit ledger (SPEC.md §4, ARCHITECTURE.md
    step 10). The caller owns the commit, matching every other pipeline
    function's existing "mutate, then commit" shape.
    """
    entry = AuditLogEntry(
        project_id=project_id,
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        actor=actor,
        payload=payload or {},
    )
    db.add(entry)
    return entry
