import logging
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Decision,
    DiscordGuild,
    DriveDraftEdit,
    GoogleDriveInstallation,
    Message,
    Project,
    ProjectChannel,
    RepoDocument,
    User,
    utcnow,
)
from app.db.session import get_db
from app.ingestion.google.client import google_drive_client
from app.pipeline.audit import log_event
from app.pipeline.drive_draft import find_target_drive_section, generate_draft, target_heading_text
from app.web.deps import require_admin, require_login
from app.web.templating import templates

router = APIRouter(tags=["decisions"])
logger = logging.getLogger("arbordocs.web.decisions")


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

    drive_installation = await db.scalar(
        select(GoogleDriveInstallation).where(GoogleDriveInstallation.project_id == project_id)
    )
    drafted_edit = await db.scalar(select(DriveDraftEdit).where(DriveDraftEdit.decision_id == decision.id))
    drafted_edit_target = (
        await db.get(RepoDocument, drafted_edit.repo_document_id) if drafted_edit is not None else None
    )
    drive_sections = (
        (
            await db.scalars(
                select(RepoDocument).where(
                    RepoDocument.project_id == project_id, RepoDocument.kind == "drive_section"
                )
            )
        ).all()
        if drive_installation is not None and drafted_edit is None
        else []
    )

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
            "drive_installation": drive_installation,
            "drafted_edit": drafted_edit,
            "drafted_edit_target": drafted_edit_target,
            "drive_sections": drive_sections,
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


async def _generate_and_store_drive_draft(db: AsyncSession, decision: Decision, user: User) -> None:
    """Issue #26 (Drive piece 2): retrieval + LLM draft generation, run
    synchronously right after a decision is approved (per the user's
    explicit choice of inline-in-approve_decision over a separate
    worker-polled stage) so the human sees the draft immediately.

    A no-op (not an error) if the project has no connected Drive
    installation or no related drive_section scores above threshold —
    the human sees a manual-picker state on the decision detail page in
    that case instead of a draft preview. Callers must wrap this in a
    broad try/except: a draft-generation failure must never block the
    approval itself from succeeding (same "log and continue" policy as
    the decider-DM step in app/worker/main.py's run_extraction).
    """
    installation = await db.scalar(
        select(GoogleDriveInstallation).where(GoogleDriveInstallation.project_id == decision.project_id)
    )
    if installation is None:
        return

    target = await find_target_drive_section(db, decision)
    if target is None:
        return

    draft_content = await generate_draft(decision, target)

    existing = await db.scalar(select(DriveDraftEdit).where(DriveDraftEdit.decision_id == decision.id))
    if existing is not None:
        existing.draft_content = draft_content
        existing.repo_document_id = target.id
        existing.status = "drafted"
        existing.applied_at = None
    else:
        db.add(
            DriveDraftEdit(
                decision_id=decision.id,
                repo_document_id=target.id,
                draft_content=draft_content,
                status="drafted",
            )
        )
    await log_event(
        db,
        decision.project_id,
        "drive_draft_generated",
        "decision",
        decision.id,
        actor=user.github_login,
        payload={"repo_document_id": str(target.id)},
    )


@router.post("/decisions/{decision_id}/approve")
async def approve_decision(
    decision_id: uuid.UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    decision = await db.get(Decision, decision_id)
    if decision is None:
        raise HTTPException(status_code=404)
    old_status = decision.status
    decision.status = "active"
    await log_event(
        db,
        decision.project_id,
        "decision_approved",
        "decision",
        decision.id,
        actor=user.github_login,
        payload={"old_status": old_status, "new_status": "active"},
    )
    await db.commit()

    try:
        await _generate_and_store_drive_draft(db, decision, user)
        await db.commit()
    except Exception:
        logger.exception("drive draft generation failed: decision=%s", decision.id)
        await db.rollback()

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
    old_status = decision.status
    decision.status = "rejected"
    await log_event(
        db,
        decision.project_id,
        "decision_rejected",
        "decision",
        decision.id,
        actor=user.github_login,
        payload={"old_status": old_status, "new_status": "rejected"},
    )
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
    old_statement = decision.statement
    old_rationale = decision.rationale
    decision.statement = statement
    decision.rationale = rationale or None
    await log_event(
        db,
        decision.project_id,
        "decision_edited",
        "decision",
        decision.id,
        actor=user.github_login,
        payload={
            "old_statement": old_statement,
            "new_statement": statement,
            "old_rationale": old_rationale,
            "new_rationale": decision.rationale,
        },
    )
    await db.commit()
    return RedirectResponse(f"/projects/{decision.project_id}/decisions/{decision.id}", status_code=303)


@router.post("/decisions/{decision_id}/drive-draft/regenerate")
async def regenerate_drive_draft(
    decision_id: uuid.UUID,
    repo_document_id: uuid.UUID | None = Form(None),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Re-runs draft generation against a target Drive section (issue #26).

    `repo_document_id` lets the human pick a target manually (the
    decision-detail page's manual-picker fallback, shown when no confident
    embedding match was found) — otherwise reuses the existing
    DriveDraftEdit row's target, replacing its content and resetting
    status to "drafted".
    """
    decision = await db.get(Decision, decision_id)
    if decision is None:
        raise HTTPException(status_code=404)

    drafted_edit = await db.scalar(select(DriveDraftEdit).where(DriveDraftEdit.decision_id == decision.id))

    target_id = repo_document_id or (drafted_edit.repo_document_id if drafted_edit else None)
    if target_id is None:
        raise HTTPException(status_code=400, detail="No target Drive section specified")

    target = await db.get(RepoDocument, target_id)
    if target is None or target.project_id != decision.project_id or target.kind != "drive_section":
        raise HTTPException(status_code=404)

    draft_content = await generate_draft(decision, target)

    if drafted_edit is not None:
        drafted_edit.repo_document_id = target.id
        drafted_edit.draft_content = draft_content
        drafted_edit.status = "drafted"
        drafted_edit.applied_at = None
    else:
        db.add(
            DriveDraftEdit(
                decision_id=decision.id,
                repo_document_id=target.id,
                draft_content=draft_content,
                status="drafted",
            )
        )

    await log_event(
        db,
        decision.project_id,
        "drive_draft_generated",
        "decision",
        decision.id,
        actor=user.github_login,
        payload={"repo_document_id": str(target.id)},
    )
    await db.commit()
    return RedirectResponse(f"/projects/{decision.project_id}/decisions/{decision.id}", status_code=303)


@router.post("/decisions/{decision_id}/drive-draft/apply")
async def apply_drive_draft(
    decision_id: uuid.UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Writes a drafted edit into the real Google Doc (issue #26) — the
    second, separate explicit confirmation beyond approving the decision.

    Re-locates the target section's live character-offset range fresh,
    immediately before writing (never reusing any previously-computed
    range — see GoogleDriveClient.find_section_range's docstring on why).
    Fails closed: if the section can't be confidently re-located (the doc
    changed too much upstream of drafting), flips status to "failed" and
    redirects back without writing anything, so the human can regenerate.
    """
    decision = await db.get(Decision, decision_id)
    if decision is None:
        raise HTTPException(status_code=404)

    drafted_edit = await db.scalar(select(DriveDraftEdit).where(DriveDraftEdit.decision_id == decision.id))
    if drafted_edit is None:
        raise HTTPException(status_code=404)

    target = await db.get(RepoDocument, drafted_edit.repo_document_id)
    installation = await db.scalar(
        select(GoogleDriveInstallation).where(GoogleDriveInstallation.project_id == decision.project_id)
    )
    if target is None or installation is None or target.source_file_id is None:
        raise HTTPException(status_code=404)

    access_token = await google_drive_client.refresh_access_token(installation.refresh_token)
    heading_text = target_heading_text(target)
    section_range = await google_drive_client.find_section_range(
        access_token, target.source_file_id, heading_text
    )

    if section_range is None:
        drafted_edit.status = "failed"
        await log_event(
            db,
            decision.project_id,
            "drive_doc_update_failed",
            "decision",
            decision.id,
            actor=user.github_login,
            payload={"reason": "target section could not be re-located in the live doc"},
        )
        await db.commit()
        return RedirectResponse(f"/projects/{decision.project_id}/decisions/{decision.id}", status_code=303)

    start_index, end_index = section_range
    before_content = target.content
    await google_drive_client.apply_edit(
        access_token, target.source_file_id, start_index, end_index, drafted_edit.draft_content
    )

    drafted_edit.status = "applied"
    drafted_edit.applied_at = utcnow()
    await log_event(
        db,
        decision.project_id,
        "drive_doc_updated",
        "decision",
        decision.id,
        actor=user.github_login,
        payload={"before": before_content, "after": drafted_edit.draft_content},
    )
    await db.commit()
    return RedirectResponse(f"/projects/{decision.project_id}/decisions/{decision.id}", status_code=303)
