import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Decision, DiscordGuild, Message, Project, ProjectChannel, User
from app.db.session import get_db
from app.web.deps import require_admin, require_login
from app.web.templating import templates

router = APIRouter(tags=["decisions"])


async def _resolve_message_url(db: AsyncSession, channel_id: str, message_id: str) -> str | None:
    """Discord permalinks need the guild_id, which Decision doesn't store
    directly — resolve it via the channel's ProjectChannel/DiscordGuild link.
    Returns None (caller falls back to plain text) if the channel was since
    detached and no link can be resolved.
    """
    guild_id = await db.scalar(
        select(DiscordGuild.guild_id)
        .join(ProjectChannel, ProjectChannel.discord_guild_id == DiscordGuild.id)
        .where(ProjectChannel.channel_id == channel_id)
    )
    if guild_id is None:
        return None
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


@router.get("/projects/{project_id}/decisions")
async def decisions_queue(
    request: Request,
    project_id: uuid.UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404)

    decisions = await db.scalars(
        select(Decision)
        .where(Decision.project_id == project_id, Decision.status == "proposed")
        .order_by(Decision.timestamp)
    )
    return templates.TemplateResponse(
        request,
        "decisions_queue.html",
        {"user": user, "project": project, "decisions": decisions.all()},
    )


@router.get("/projects/{project_id}/decisions/{decision_id}")
async def decision_detail(
    request: Request,
    project_id: uuid.UUID,
    decision_id: uuid.UUID,
    user: User = Depends(require_admin),
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

    return templates.TemplateResponse(
        request,
        "decision_detail.html",
        {
            "user": user,
            "project": project,
            "decision": decision,
            "message_links": message_links,
            "supersedes": supersedes,
            "superseded_by": superseded_by,
        },
    )


@router.get("/decisions/{decision_id}/messages/{message_id}/open")
async def open_source_message(
    decision_id: uuid.UUID,
    message_id: str,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Same-origin redirect to a message's Discord permalink — the template
    never embeds the external discord.com URL directly in an `href`, only
    this relative, server-validated path (avoids a var-in-href XSS finding
    on a value that's always server-built, never user-controlled).

    require_login, not require_admin: both the admin review UI and the
    read-only portal link through this same route, and the portal is only
    login-gated (ADR-0008), not admin-gated.
    """
    decision = await db.get(Decision, decision_id)
    if decision is None or message_id not in decision.message_ids:
        raise HTTPException(status_code=404)

    url = await _resolve_message_url(db, decision.channel_id, message_id)
    if url is None:
        raise HTTPException(status_code=404)
    return RedirectResponse(url)


@router.post("/decisions/{decision_id}/approve")
async def approve_decision(
    decision_id: uuid.UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    decision = await db.get(Decision, decision_id)
    if decision is None:
        raise HTTPException(status_code=404)
    decision.status = "active"
    await db.commit()
    return RedirectResponse(f"/projects/{decision.project_id}/decisions", status_code=303)


@router.post("/decisions/{decision_id}/reject")
async def reject_decision(
    decision_id: uuid.UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    decision = await db.get(Decision, decision_id)
    if decision is None:
        raise HTTPException(status_code=404)
    decision.status = "rejected"
    await db.commit()
    return RedirectResponse(f"/projects/{decision.project_id}/decisions", status_code=303)


@router.post("/decisions/{decision_id}/edit")
async def edit_decision(
    decision_id: uuid.UUID,
    statement: str = Form(...),
    rationale: str = Form(""),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    decision = await db.get(Decision, decision_id)
    if decision is None:
        raise HTTPException(status_code=404)
    decision.statement = statement
    decision.rationale = rationale or None
    await db.commit()
    return RedirectResponse(f"/projects/{decision.project_id}/decisions/{decision.id}", status_code=303)
