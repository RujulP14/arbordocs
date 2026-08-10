import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.web.auth as auth_module
from app.db.models import User
from app.web.main import app


@pytest.fixture
async def client(db_session, monkeypatch):
    from app.db.session import get_db

    session_maker = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(auth_module, "async_session", session_maker)

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    async def _fake_exchange_oauth_code(code):
        return {"access_token": "fake-token"}

    monkeypatch.setattr(auth_module.github_app_client, "exchange_oauth_code", _fake_exchange_oauth_code)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, db_session, monkeypatch

    app.dependency_overrides.clear()


def _set_identity(monkeypatch, github_login: str, email: str | None = None):
    async def _fake_fetch_identity(access_token):
        return {"login": github_login, "email": email}

    monkeypatch.setattr(auth_module.github_app_client, "fetch_identity", _fake_fetch_identity)


async def test_new_login_creates_pending_user_and_redirects_to_pending(client):
    ac, db_session, monkeypatch = client
    _set_identity(monkeypatch, "newperson")

    login_resp = await ac.get("/auth/github/start", follow_redirects=False)
    redirect_url = login_resp.headers["location"]
    state = redirect_url.split("state=")[1]

    callback_resp = await ac.get(
        "/auth/github/callback",
        params={"code": "fake-code", "state": state},
        follow_redirects=False,
    )

    assert callback_resp.status_code == 307
    assert callback_resp.headers["location"].startswith("/auth/github/pending")

    # No authenticated session was created — a login-gated page bounces back.
    projects_resp = await ac.get("/projects", follow_redirects=False)
    assert projects_resp.status_code == 303
    assert projects_resp.headers["location"] == "/auth/github/login"

    user = await db_session.scalar(select(User).where(User.github_login == "newperson"))
    assert user is not None
    assert user.verified is False
    assert user.is_admin is False


async def test_repeat_pending_login_does_not_create_duplicate_row(client):
    ac, db_session, monkeypatch = client
    _set_identity(monkeypatch, "stillpending")

    for _ in range(2):
        login_resp = await ac.get("/auth/github/start", follow_redirects=False)
        state = login_resp.headers["location"].split("state=")[1]
        callback_resp = await ac.get(
            "/auth/github/callback",
            params={"code": "fake-code", "state": state},
            follow_redirects=False,
        )
        assert callback_resp.headers["location"].startswith("/auth/github/pending")

    users = (await db_session.scalars(select(User).where(User.github_login == "stillpending"))).all()
    assert len(users) == 1


async def test_verified_non_admin_login_succeeds(client):
    ac, db_session, monkeypatch = client
    _set_identity(monkeypatch, "verifieduser")
    db_session.add(User(github_login="verifieduser", is_admin=False, verified=True))
    await db_session.commit()

    login_resp = await ac.get("/auth/github/start", follow_redirects=False)
    state = login_resp.headers["location"].split("state=")[1]
    callback_resp = await ac.get(
        "/auth/github/callback",
        params={"code": "fake-code", "state": state},
        follow_redirects=False,
    )

    assert callback_resp.status_code == 307
    assert callback_resp.headers["location"] == "/projects"


async def test_admin_login_succeeds(client):
    ac, db_session, monkeypatch = client
    _set_identity(monkeypatch, "adminuser")
    db_session.add(User(github_login="adminuser", is_admin=True, verified=True))
    await db_session.commit()

    login_resp = await ac.get("/auth/github/start", follow_redirects=False)
    state = login_resp.headers["location"].split("state=")[1]
    callback_resp = await ac.get(
        "/auth/github/callback",
        params={"code": "fake-code", "state": state},
        follow_redirects=False,
    )

    assert callback_resp.status_code == 307
    assert callback_resp.headers["location"] == "/projects"


async def test_deverified_user_loses_access_on_next_request(client):
    """Session cookies must not survive flipping verified=False in the DB."""
    from app.db.models import Project

    ac, db_session, monkeypatch = client
    _set_identity(monkeypatch, "wasverified")
    user = User(github_login="wasverified", is_admin=False, verified=True)
    db_session.add(user)
    await db_session.flush()
    project = Project(name="Portal Project", created_by=user.id)
    db_session.add(project)
    await db_session.commit()

    login_resp = await ac.get("/auth/github/start", follow_redirects=False)
    state = login_resp.headers["location"].split("state=")[1]
    callback_resp = await ac.get(
        "/auth/github/callback",
        params={"code": "fake-code", "state": state},
        follow_redirects=False,
    )
    assert callback_resp.headers["location"] == "/projects"

    # Still verified — portal is reachable.
    ok = await ac.get(f"/projects/{project.id}/portal", follow_redirects=False)
    assert ok.status_code == 200

    user.verified = False
    await db_session.commit()

    portal_resp = await ac.get(f"/projects/{project.id}/portal", follow_redirects=False)
    assert portal_resp.status_code == 303
    assert portal_resp.headers["location"] == "/auth/github/login"
