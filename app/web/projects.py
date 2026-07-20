import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Project, User
from app.db.session import get_db
from app.web.deps import require_admin
from app.web.templating import templates

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("")
async def list_projects(
    request: Request, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    projects = await db.scalars(select(Project).order_by(Project.created_at.desc()))
    return templates.TemplateResponse(request, "dashboard.html", {"user": user, "projects": projects.all()})


@router.post("")
async def create_project(
    name: str = Form(...),
    description: str = Form(""),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    project = Project(name=name, description=description or None, created_by=user.id)
    db.add(project)
    await db.commit()
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


@router.get("/{project_id}")
async def project_detail(
    request: Request,
    project_id: uuid.UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    project = await db.scalar(
        select(Project)
        .where(Project.id == project_id)
        .options(selectinload(Project.github_installation), selectinload(Project.channels))
    )
    return templates.TemplateResponse(request, "project_detail.html", {"user": user, "project": project})
