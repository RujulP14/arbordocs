import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GitHubInstallation, Project, User
from app.db.session import get_db
from app.ingestion.github.client import github_app_client
from app.web.deps import require_admin
from app.web.templating import templates

router = APIRouter(prefix="/integrations/github", tags=["integrations-github"])


@router.get("/connect/{project_id}")
async def connect(
    project_id: uuid.UUID, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> RedirectResponse:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404)
    return RedirectResponse(github_app_client.install_url(state=str(project_id)))


@router.get("/callback")
async def callback(
    request: Request,
    installation_id: str,
    state: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    project_id = uuid.UUID(state)
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404)

    repos = await github_app_client.list_installation_repos(installation_id)
    return templates.TemplateResponse(
        request,
        "github_repo_picker.html",
        {"user": user, "project": project, "installation_id": installation_id, "repos": repos},
    )


@router.post("/attach/{project_id}")
async def attach(
    project_id: uuid.UUID,
    installation_id: str = Form(...),
    repo_full_name: str = Form(...),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    existing = await db.scalar(select(GitHubInstallation).where(GitHubInstallation.project_id == project_id))
    if existing:
        existing.installation_id = installation_id
        existing.repo_full_name = repo_full_name
    else:
        db.add(
            GitHubInstallation(
                project_id=project_id, installation_id=installation_id, repo_full_name=repo_full_name
            )
        )
    await db.commit()
    return RedirectResponse(f"/projects/{project_id}", status_code=303)
