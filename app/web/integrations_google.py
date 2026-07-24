import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.models import GoogleDriveInstallation, Project, User
from app.db.session import get_db
from app.ingestion.google.client import google_drive_client
from app.web.deps import require_admin
from app.web.templating import templates

router = APIRouter(prefix="/integrations/google", tags=["integrations-google"])


def _callback_url() -> str:
    return f"{settings.base_url}/integrations/google/callback"


@router.get("/connect/{project_id}")
async def connect(
    project_id: uuid.UUID, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> RedirectResponse:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404)
    url = google_drive_client.oauth_authorize_url(redirect_uri=_callback_url(), state=str(project_id))
    return RedirectResponse(url)


@router.get("/callback")
async def callback(
    request: Request,
    code: str,
    state: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    project_id = uuid.UUID(state)
    project = await db.scalar(
        select(Project)
        .where(Project.id == project_id)
        .options(selectinload(Project.google_drive_installation))
    )
    if project is None:
        raise HTTPException(status_code=404)

    token_data = await google_drive_client.exchange_oauth_code(code, redirect_uri=_callback_url())
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    if not access_token or not refresh_token:
        raise HTTPException(status_code=400, detail="Google OAuth exchange failed")

    # Held server-side in the session rather than round-tripped through a
    # hidden form field — a refresh token is a long-lived credential, unlike
    # GitHub's non-secret installation_id, so it shouldn't appear in
    # rendered HTML even briefly.
    request.session["google_refresh_token"] = refresh_token

    folders = await google_drive_client.list_folders(access_token)
    return templates.TemplateResponse(
        request,
        "google_folder_picker.html",
        {"user": user, "project": project, "folders": folders},
    )


@router.post("/attach/{project_id}")
async def attach(
    request: Request,
    project_id: uuid.UUID,
    folder: str = Form(...),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    # "folder_id|folder_name" — one radio value, so id/name can't drift
    # apart (same encoding as integrations_discord.py's channel checkboxes).
    folder_id, _, folder_name = folder.partition("|")

    refresh_token = request.session.pop("google_refresh_token", None)
    if not refresh_token:
        raise HTTPException(status_code=400, detail="No pending Google OAuth session found")

    existing = await db.scalar(
        select(GoogleDriveInstallation).where(GoogleDriveInstallation.project_id == project_id)
    )
    if existing:
        existing.folder_id = folder_id
        existing.folder_name = folder_name or None
        existing.refresh_token = refresh_token
    else:
        db.add(
            GoogleDriveInstallation(
                project_id=project_id,
                folder_id=folder_id,
                folder_name=folder_name or None,
                refresh_token=refresh_token,
            )
        )
    await db.commit()
    return RedirectResponse(f"/projects/{project_id}", status_code=303)
