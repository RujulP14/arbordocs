import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Decision, Project, User
from app.db.session import get_db
from app.web.deps import require_admin
from app.web.templating import templates

router = APIRouter(prefix="/projects", tags=["projects"])


async def _decision_counts_by_project(db: AsyncSession) -> dict[uuid.UUID, tuple[int, int]]:
    """Returns {project_id: (proposed_count, active_count)} in one grouped
    query rather than one count query per project row.
    """
    rows = await db.execute(
        select(
            Decision.project_id,
            func.count(case((Decision.status == "proposed", 1))),
            func.count(case((Decision.status == "active", 1))),
        ).group_by(Decision.project_id)
    )
    return {project_id: (proposed, active) for project_id, proposed, active in rows}


@router.get("")
async def list_projects(
    request: Request, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    projects = (await db.scalars(select(Project).order_by(Project.created_at.desc()))).all()
    counts = await _decision_counts_by_project(db)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "projects": projects,
            "counts": {pid: {"proposed": p, "active": a} for pid, (p, a) in counts.items()},
        },
    )


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

    proposed_count, active_count = (
        await db.execute(
            select(
                func.count(case((Decision.status == "proposed", 1))),
                func.count(case((Decision.status == "active", 1))),
            ).where(Decision.project_id == project_id)
        )
    ).one()
    recent_decisions = (
        await db.scalars(
            select(Decision)
            .where(Decision.project_id == project_id)
            .order_by(Decision.timestamp.desc())
            .limit(5)
        )
    ).all()

    return templates.TemplateResponse(
        request,
        "project_detail.html",
        {
            "user": user,
            "project": project,
            "proposed_count": proposed_count,
            "active_count": active_count,
            "recent_decisions": recent_decisions,
        },
    )
