import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLogEntry, Decision, Message, Project, User
from app.db.session import get_db
from app.web.decisions import _resolve_message_url
from app.web.deps import require_login
from app.web.templating import templates

router = APIRouter(tags=["portal"])


@router.get("/projects/{project_id}/portal")
async def portal_list(
    request: Request,
    project_id: uuid.UUID,
    type: str | None = None,
    scope: str | None = None,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404)

    query = select(Decision).where(Decision.project_id == project_id, Decision.status == "active")
    if type:
        query = query.where(Decision.type == type)
    if scope:
        query = query.where(Decision.scope == scope)
    query = query.order_by(Decision.timestamp.desc())

    decisions = await db.scalars(query)
    return templates.TemplateResponse(
        request,
        "portal_list.html",
        {
            "user": user,
            "project": project,
            "decisions": decisions.all(),
            "type_filter": type or "",
            "scope_filter": scope or "",
        },
    )


@router.get("/projects/{project_id}/portal/{decision_id}")
async def portal_detail(
    request: Request,
    project_id: uuid.UUID,
    decision_id: uuid.UUID,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404)

    decision = await db.get(Decision, decision_id)
    if decision is None or decision.project_id != project_id:
        raise HTTPException(status_code=404)

    source_messages = (
        await db.scalars(
            select(Message)
            .where(Message.discord_message_id.in_(decision.message_ids))
            .order_by(Message.created_at)
        )
    ).all()
    messages_by_id = {m.discord_message_id: m for m in source_messages}

    message_links = [
        {
            "id": mid,
            "message": messages_by_id.get(mid),
            "has_link": await _resolve_message_url(db, decision.channel_id, mid) is not None,
        }
        for mid in decision.message_ids
    ]

    supersedes = await db.get(Decision, decision.supersedes) if decision.supersedes else None
    superseded_by = await db.get(Decision, decision.superseded_by) if decision.superseded_by else None

    audit_entries = (
        await db.scalars(
            select(AuditLogEntry)
            .where(AuditLogEntry.subject_type == "decision", AuditLogEntry.subject_id == decision.id)
            .order_by(AuditLogEntry.created_at)
        )
    ).all()

    return templates.TemplateResponse(
        request,
        "portal_detail.html",
        {
            "user": user,
            "project": project,
            "decision": decision,
            "message_links": message_links,
            "supersedes": supersedes,
            "superseded_by": superseded_by,
            "audit_entries": audit_entries,
        },
    )
