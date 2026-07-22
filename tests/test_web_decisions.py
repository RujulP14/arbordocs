import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import Decision, DiscordGuild, Message, Project, ProjectChannel, User
from app.db.session import get_db
from app.web.deps import require_admin
from app.web.main import app


@pytest.fixture
async def client(db_session):
    async def _override_get_db():
        yield db_session

    admin = User(github_login="octocat", is_admin=True)
    db_session.add(admin)
    await db_session.flush()

    async def _override_require_admin():
        return admin

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[require_admin] = _override_require_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, admin, db_session

    app.dependency_overrides.clear()


async def _make_project(db_session, admin: User) -> Project:
    project = Project(name="Test Project", created_by=admin.id)
    db_session.add(project)
    await db_session.flush()
    return project


def _decision(project_id, **overrides) -> Decision:
    defaults = dict(
        project_id=project_id,
        candidate_id=uuid.uuid4(),
        statement="placeholder decision",
        type="technical",
        channel_id="chan-1",
        message_ids=["msg-1"],
        timestamp=datetime.now(UTC),
        authority_tier="medium",
        status="proposed",
        confidence=0.9,
    )
    defaults.update(overrides)
    return Decision(**defaults)


async def test_queue_only_shows_proposed_decisions(client):
    ac, admin, db_session = client
    project = await _make_project(db_session, admin)

    proposed = _decision(project.id, statement="proposed one", status="proposed")
    active = _decision(project.id, statement="active one", status="active")
    rejected = _decision(project.id, statement="rejected one", status="rejected")
    db_session.add_all([proposed, active, rejected])
    await db_session.commit()

    resp = await ac.get(f"/projects/{project.id}/decisions")

    assert resp.status_code == 200
    assert "proposed one" in resp.text
    assert "active one" not in resp.text
    assert "rejected one" not in resp.text


async def test_approve_flips_status_to_active(client):
    ac, admin, db_session = client
    project = await _make_project(db_session, admin)
    decision = _decision(project.id)
    db_session.add(decision)
    await db_session.commit()

    resp = await ac.post(f"/decisions/{decision.id}/approve", follow_redirects=False)

    assert resp.status_code == 303
    await db_session.refresh(decision)
    assert decision.status == "active"


async def test_reject_flips_status_to_rejected(client):
    ac, admin, db_session = client
    project = await _make_project(db_session, admin)
    decision = _decision(project.id)
    db_session.add(decision)
    await db_session.commit()

    resp = await ac.post(f"/decisions/{decision.id}/reject", follow_redirects=False)

    assert resp.status_code == 303
    await db_session.refresh(decision)
    assert decision.status == "rejected"


async def test_edit_updates_statement_and_rationale_without_touching_embedding(client):
    ac, admin, db_session = client
    project = await _make_project(db_session, admin)
    decision = _decision(project.id, statement="original", statement_embedding=[1.0] + [0.0] * 383)
    db_session.add(decision)
    await db_session.commit()

    resp = await ac.post(
        f"/decisions/{decision.id}/edit",
        data={"statement": "corrected statement", "rationale": "because reasons"},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    await db_session.refresh(decision)
    assert decision.statement == "corrected statement"
    assert decision.rationale == "because reasons"
    assert decision.statement_embedding == [1.0] + [0.0] * 383


async def test_detail_shows_reconciliation_flags_when_present(client):
    ac, admin, db_session = client
    project = await _make_project(db_session, admin)
    decision = _decision(
        project.id,
        reconciliation={
            "state": "unverified",
            "related_code": ["app/routes.py#list_users"],
            "related_docs": ["docs/api.md#pagination"],
            "notes": None,
        },
    )
    db_session.add(decision)
    await db_session.commit()

    resp = await ac.get(f"/projects/{project.id}/decisions/{decision.id}")

    assert resp.status_code == 200
    assert "app/routes.py#list_users" in resp.text
    assert "docs/api.md#pagination" in resp.text


async def test_detail_shows_not_yet_reconciled_when_reconciliation_is_none(client):
    ac, admin, db_session = client
    project = await _make_project(db_session, admin)
    decision = _decision(project.id, reconciliation=None)
    db_session.add(decision)
    await db_session.commit()

    resp = await ac.get(f"/projects/{project.id}/decisions/{decision.id}")

    assert resp.status_code == 200
    assert "Not yet reconciled" in resp.text


async def test_message_link_falls_back_to_plain_text_without_channel(client):
    ac, admin, db_session = client
    project = await _make_project(db_session, admin)
    decision = _decision(project.id, channel_id="unattached-channel", message_ids=["msg-1"])
    db_session.add(decision)
    await db_session.commit()

    resp = await ac.get(f"/projects/{project.id}/decisions/{decision.id}")

    assert resp.status_code == 200
    assert "msg-1" in resp.text
    assert "discord.com/channels" not in resp.text


async def test_message_link_resolved_when_channel_attached(client):
    ac, admin, db_session = client
    project = await _make_project(db_session, admin)

    guild = DiscordGuild(guild_id="guild-1", guild_name="Test Guild")
    db_session.add(guild)
    await db_session.flush()
    channel = ProjectChannel(
        project_id=project.id, discord_guild_id=guild.id, channel_id="chan-1", channel_name="eng"
    )
    db_session.add(channel)
    await db_session.flush()

    decision = _decision(project.id, channel_id="chan-1", message_ids=["msg-1"])
    db_session.add(decision)
    await db_session.commit()

    resp = await ac.get(f"/projects/{project.id}/decisions/{decision.id}")

    assert resp.status_code == 200
    assert "https://discord.com/channels/guild-1/chan-1/msg-1" in resp.text


async def test_detail_renders_real_source_message_content(client):
    ac, admin, db_session = client
    project = await _make_project(db_session, admin)

    message = Message(
        project_id=project.id,
        channel_id="chan-1",
        discord_message_id="msg-1",
        author_id="user-1",
        author_name="alice",
        content="use cursor-based pagination",
        created_at=datetime.now(UTC),
    )
    db_session.add(message)
    await db_session.flush()

    decision = _decision(project.id, channel_id="chan-1", message_ids=["msg-1"])
    db_session.add(decision)
    await db_session.commit()

    resp = await ac.get(f"/projects/{project.id}/decisions/{decision.id}")

    assert resp.status_code == 200
    assert "alice" in resp.text
    assert "use cursor-based pagination" in resp.text


async def test_detail_shows_placeholder_for_missing_message(client):
    ac, admin, db_session = client
    project = await _make_project(db_session, admin)
    decision = _decision(project.id, channel_id="chan-1", message_ids=["msg-deleted"])
    db_session.add(decision)
    await db_session.commit()

    resp = await ac.get(f"/projects/{project.id}/decisions/{decision.id}")

    assert resp.status_code == 200
    assert "was not found" in resp.text
