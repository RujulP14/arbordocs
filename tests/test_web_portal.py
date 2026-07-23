import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import Decision, Project, User
from app.db.session import get_db
from app.web.deps import require_login
from app.web.main import app


@pytest.fixture
async def client(db_session):
    async def _override_get_db():
        yield db_session

    user = User(github_login="verified-user", is_admin=False)
    db_session.add(user)
    await db_session.flush()

    async def _override_require_login():
        return user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[require_login] = _override_require_login

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, user, db_session

    app.dependency_overrides.clear()


@pytest.fixture
async def unauthenticated_client(db_session):
    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    # require_login intentionally left unoverridden — exercises the real
    # dependency, which reads an empty session and redirects.

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, db_session

    app.dependency_overrides.clear()


async def _make_project(db_session, user: User) -> Project:
    project = Project(name="Test Project", created_by=user.id)
    db_session.add(project)
    await db_session.flush()
    return project


def _decision(project_id, **overrides) -> Decision:
    defaults = dict(
        project_id=project_id,
        candidate_id=uuid.uuid4(),
        statement="placeholder decision",
        type="technical",
        scope=None,
        channel_id="chan-1",
        message_ids=[],
        timestamp=datetime.now(UTC),
        authority_tier="medium",
        status="active",
        confidence=0.9,
    )
    defaults.update(overrides)
    return Decision(**defaults)


async def test_portal_only_shows_active_decisions(client):
    ac, user, db_session = client
    project = await _make_project(db_session, user)

    active = _decision(project.id, statement="active one", status="active")
    proposed = _decision(project.id, statement="proposed one", status="proposed")
    rejected = _decision(project.id, statement="rejected one", status="rejected")
    superseded = _decision(project.id, statement="superseded one", status="superseded")
    db_session.add_all([active, proposed, rejected, superseded])
    await db_session.commit()

    resp = await ac.get(f"/projects/{project.id}/portal")

    assert resp.status_code == 200
    assert "active one" in resp.text
    assert "proposed one" not in resp.text
    assert "rejected one" not in resp.text
    assert "superseded one" not in resp.text


async def test_portal_filters_by_type(client):
    ac, user, db_session = client
    project = await _make_project(db_session, user)

    technical = _decision(project.id, statement="technical decision", type="technical")
    policy = _decision(project.id, statement="policy decision", type="policy")
    db_session.add_all([technical, policy])
    await db_session.commit()

    resp = await ac.get(f"/projects/{project.id}/portal", params={"type": "policy"})

    assert resp.status_code == 200
    assert "policy decision" in resp.text
    assert "technical decision" not in resp.text


async def test_portal_filters_by_scope(client):
    ac, user, db_session = client
    project = await _make_project(db_session, user)

    backend = _decision(project.id, statement="backend decision", scope="backend/api")
    frontend = _decision(project.id, statement="frontend decision", scope="frontend/ui")
    db_session.add_all([backend, frontend])
    await db_session.commit()

    resp = await ac.get(f"/projects/{project.id}/portal", params={"scope": "backend/api"})

    assert resp.status_code == 200
    assert "backend decision" in resp.text
    assert "frontend decision" not in resp.text


async def test_portal_detail_shows_reconciliation_and_supersession(client):
    ac, user, db_session = client
    project = await _make_project(db_session, user)

    old_decision = _decision(project.id, statement="old decision", status="superseded")
    db_session.add(old_decision)
    await db_session.flush()

    decision = _decision(
        project.id,
        statement="new decision",
        supersedes=old_decision.id,
        reconciliation={
            "state": "unverified",
            "related_code": ["app/routes.py#list_users"],
            "related_docs": ["docs/api.md#pagination"],
            "notes": None,
        },
    )
    db_session.add(decision)
    old_decision.superseded_by = decision.id
    await db_session.commit()

    resp = await ac.get(f"/projects/{project.id}/portal/{decision.id}")

    assert resp.status_code == 200
    assert "app/routes.py#list_users" in resp.text
    assert "docs/api.md#pagination" in resp.text
    assert "old decision" in resp.text


async def test_portal_detail_has_no_review_actions(client):
    ac, user, db_session = client
    project = await _make_project(db_session, user)
    decision = _decision(project.id)
    db_session.add(decision)
    await db_session.commit()

    resp = await ac.get(f"/projects/{project.id}/portal/{decision.id}")

    assert resp.status_code == 200
    assert "/approve" not in resp.text
    assert "/reject" not in resp.text
    assert "/edit" not in resp.text
    assert "Edit statement" not in resp.text


async def test_unauthenticated_request_redirects_to_login(unauthenticated_client):
    ac, db_session = unauthenticated_client
    admin = User(github_login="octocat", is_admin=True)
    db_session.add(admin)
    await db_session.flush()
    project = await _make_project(db_session, admin)
    await db_session.commit()

    resp = await ac.get(f"/projects/{project.id}/portal", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/auth/github/login"
