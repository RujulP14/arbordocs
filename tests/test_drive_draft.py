import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import app.pipeline.drive_draft as drive_draft_module
import app.web.decisions as decisions_module
from app.db.models import (
    AuditLogEntry,
    Decision,
    DriveDraftEdit,
    GoogleDriveInstallation,
    Project,
    RepoDocument,
    User,
)
from app.db.session import get_db
from app.pipeline.drive_draft import find_target_drive_section, generate_draft, target_heading_text
from app.web.deps import require_admin, require_login
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
    app.dependency_overrides[require_login] = _override_require_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, admin, db_session

    app.dependency_overrides.clear()


async def _make_project(db_session, admin: User) -> Project:
    project = Project(name="Test Project", created_by=admin.id)
    db_session.add(project)
    await db_session.flush()
    return project


async def _make_project_only(db_session) -> Project:
    admin = User(github_login="octocat", is_admin=True)
    db_session.add(admin)
    await db_session.flush()
    project = Project(name="Test Project", created_by=admin.id)
    db_session.add(project)
    await db_session.flush()
    return project


def _decision(project_id, **overrides) -> Decision:
    defaults = dict(
        project_id=project_id,
        candidate_id=uuid.uuid4(),
        statement="Use cursor-based pagination for the API",
        statement_embedding=[1.0] + [0.0] * 383,
        rationale="Offset pagination times out for large tables",
        scope="backend/api",
        type="technical",
        channel_id="chan-1",
        message_ids=[],
        timestamp=datetime.now(UTC),
        authority_tier="medium",
        status="proposed",
        confidence=0.9,
    )
    defaults.update(overrides)
    return Decision(**defaults)


def _drive_section(project_id, **overrides) -> RepoDocument:
    defaults = dict(
        project_id=project_id,
        kind="drive_section",
        path="API Guidelines",
        symbol_name=None,
        source_file_id="doc-file-1",
        anchor="pagination",
        content="## Pagination\n\nUse offset-based pagination.",
        embedding=[1.0] + [0.0] * 383,
    )
    defaults.update(overrides)
    return RepoDocument(**defaults)


def _patch_draft_llm(monkeypatch, draft_contents: list[str]) -> None:
    """Replaces drive_draft's groq caller with a canned one, popping the
    next draft_content per call — patched at the _PROVIDER_CALLERS dict
    entry (looked up dynamically inside generate_draft) so it takes effect
    regardless of whether generate_draft is called directly or indirectly
    through a web route.
    """
    contents = list(draft_contents)

    def _fake_call(_client, _draft_input):
        return {"draft_content": contents.pop(0)}

    monkeypatch.setitem(drive_draft_module._PROVIDER_CALLERS, "groq", (_fake_call, lambda: None))


class FakeGoogleDriveClient:
    def __init__(self, section_range: tuple[int, int] | None) -> None:
        self.section_range = section_range
        self.applied_calls: list[tuple] = []

    async def refresh_access_token(self, refresh_token: str) -> str:
        return "fake-access-token"

    async def find_section_range(self, access_token, file_id, heading_text):
        return self.section_range

    async def apply_edit(self, access_token, file_id, start_index, end_index, new_content) -> None:
        self.applied_calls.append((file_id, start_index, end_index, new_content))


def test_target_heading_text_strips_markdown_prefix():
    doc = _drive_section(uuid.uuid4(), content="## Pagination\n\nBody text.")
    assert target_heading_text(doc) == "Pagination"


async def test_find_target_drive_section_returns_top_scoring_drive_section(db_session):
    project = await _make_project_only(db_session)
    embedding = [1.0] + [0.0] * 383
    decision = _decision(project.id, statement_embedding=embedding)
    section = _drive_section(project.id, embedding=embedding)
    other_kind = RepoDocument(
        project_id=project.id,
        kind="doc_section",
        path="docs/x.md",
        anchor="x",
        content="x",
        embedding=embedding,
    )
    db_session.add_all([decision, section, other_kind])
    await db_session.commit()

    target = await find_target_drive_section(db_session, decision)

    assert target.id == section.id


async def test_find_target_drive_section_returns_none_without_embedding(db_session):
    project = await _make_project_only(db_session)
    decision = _decision(project.id, statement_embedding=None)
    db_session.add(decision)
    await db_session.commit()

    assert await find_target_drive_section(db_session, decision) is None


async def test_find_target_drive_section_returns_none_when_no_match_above_threshold(db_session):
    project = await _make_project_only(db_session)
    decision = _decision(project.id, statement_embedding=[1.0] + [0.0] * 383)
    section = _drive_section(project.id, embedding=[0.0, 1.0] + [0.0] * 382)
    db_session.add_all([decision, section])
    await db_session.commit()

    assert await find_target_drive_section(db_session, decision) is None


async def test_generate_draft_calls_llm_with_section_and_decision_content(fake_groq_client):
    target = _drive_section(uuid.uuid4())
    decision = _decision(target.project_id, statement="Use cursor pagination")
    fake_client = fake_groq_client([{"draft_content": "## Pagination\n\nUse cursor pagination."}])

    draft = await generate_draft(decision, target, client=fake_client, provider="groq")

    assert draft == "## Pagination\n\nUse cursor pagination."
    assert "Use cursor pagination" in fake_client.last_call_kwargs["messages"][1]["content"]
    assert "Use offset-based pagination" in fake_client.last_call_kwargs["messages"][1]["content"]


async def test_approve_generates_and_stores_drive_draft_when_confident_match_exists(client, monkeypatch):
    ac, admin, db_session = client
    project = await _make_project(db_session, admin)
    embedding = [1.0] + [0.0] * 383

    db_session.add(
        GoogleDriveInstallation(project_id=project.id, folder_id="folder-1", refresh_token="refresh-1")
    )
    section = _drive_section(project.id, embedding=embedding)
    decision = _decision(project.id, statement_embedding=embedding)
    db_session.add_all([section, decision])
    await db_session.commit()

    _patch_draft_llm(monkeypatch, ["## Pagination\n\nUse cursor-based pagination."])

    resp = await ac.post(f"/decisions/{decision.id}/approve", follow_redirects=False)

    assert resp.status_code == 303
    drafted = await db_session.scalar(select(DriveDraftEdit).where(DriveDraftEdit.decision_id == decision.id))
    assert drafted is not None
    assert drafted.status == "drafted"
    assert drafted.draft_content == "## Pagination\n\nUse cursor-based pagination."
    assert drafted.repo_document_id == section.id

    entries = (
        await db_session.scalars(
            select(AuditLogEntry).where(
                AuditLogEntry.subject_id == decision.id, AuditLogEntry.event_type == "drive_draft_generated"
            )
        )
    ).all()
    assert len(entries) == 1


async def test_approve_no_match_leaves_no_draft_for_manual_pick(client):
    ac, admin, db_session = client
    project = await _make_project(db_session, admin)

    db_session.add(
        GoogleDriveInstallation(project_id=project.id, folder_id="folder-1", refresh_token="refresh-1")
    )
    section = _drive_section(project.id, embedding=[0.0, 1.0] + [0.0] * 382)
    decision = _decision(project.id, statement_embedding=[1.0] + [0.0] * 383)
    db_session.add_all([section, decision])
    await db_session.commit()

    resp = await ac.post(f"/decisions/{decision.id}/approve", follow_redirects=False)
    assert resp.status_code == 303

    drafted = await db_session.scalar(select(DriveDraftEdit).where(DriveDraftEdit.decision_id == decision.id))
    assert drafted is None

    detail_resp = await ac.get(f"/projects/{project.id}/decisions/{decision.id}")
    assert detail_resp.status_code == 200
    assert "No related Drive doc section was found automatically" in detail_resp.text
    assert "API Guidelines#pagination" in detail_resp.text


async def test_regenerate_replaces_draft_content_and_resets_status(client, monkeypatch):
    ac, admin, db_session = client
    project = await _make_project(db_session, admin)
    embedding = [1.0] + [0.0] * 383

    db_session.add(
        GoogleDriveInstallation(project_id=project.id, folder_id="folder-1", refresh_token="refresh-1")
    )
    section = _drive_section(project.id, embedding=embedding)
    decision = _decision(project.id, statement_embedding=embedding, status="active")
    db_session.add_all([section, decision])
    await db_session.flush()
    drafted = DriveDraftEdit(
        decision_id=decision.id,
        repo_document_id=section.id,
        draft_content="stale draft",
        status="applied",
    )
    db_session.add(drafted)
    await db_session.commit()

    _patch_draft_llm(monkeypatch, ["## Pagination\n\nRegenerated content."])

    resp = await ac.post(
        f"/decisions/{decision.id}/drive-draft/regenerate",
        data={"repo_document_id": str(section.id)},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    await db_session.refresh(drafted)
    assert drafted.draft_content == "## Pagination\n\nRegenerated content."
    assert drafted.status == "drafted"
    assert drafted.applied_at is None


async def test_apply_succeeds_and_logs_before_after(client, monkeypatch):
    ac, admin, db_session = client
    project = await _make_project(db_session, admin)

    db_session.add(
        GoogleDriveInstallation(project_id=project.id, folder_id="folder-1", refresh_token="refresh-1")
    )
    section = _drive_section(project.id, content="## Pagination\n\nOld content.")
    decision = _decision(project.id, status="active")
    db_session.add_all([section, decision])
    await db_session.flush()
    drafted = DriveDraftEdit(
        decision_id=decision.id,
        repo_document_id=section.id,
        draft_content="## Pagination\n\nNew content.",
        status="drafted",
    )
    db_session.add(drafted)
    await db_session.commit()

    fake_drive = FakeGoogleDriveClient(section_range=(10, 40))
    monkeypatch.setattr(decisions_module, "google_drive_client", fake_drive)

    resp = await ac.post(f"/decisions/{decision.id}/drive-draft/apply", follow_redirects=False)
    assert resp.status_code == 303

    await db_session.refresh(drafted)
    assert drafted.status == "applied"
    assert drafted.applied_at is not None
    assert fake_drive.applied_calls == [("doc-file-1", 10, 40, "## Pagination\n\nNew content.")]

    entries = (
        await db_session.scalars(
            select(AuditLogEntry).where(
                AuditLogEntry.subject_id == decision.id, AuditLogEntry.event_type == "drive_doc_updated"
            )
        )
    ).all()
    assert len(entries) == 1
    assert entries[0].payload["before"] == "## Pagination\n\nOld content."
    assert entries[0].payload["after"] == "## Pagination\n\nNew content."


async def test_apply_fails_closed_when_section_not_relocated(client, monkeypatch):
    ac, admin, db_session = client
    project = await _make_project(db_session, admin)

    db_session.add(
        GoogleDriveInstallation(project_id=project.id, folder_id="folder-1", refresh_token="refresh-1")
    )
    section = _drive_section(project.id)
    decision = _decision(project.id, status="active")
    db_session.add_all([section, decision])
    await db_session.flush()
    drafted = DriveDraftEdit(
        decision_id=decision.id,
        repo_document_id=section.id,
        draft_content="## Pagination\n\nNew content.",
        status="drafted",
    )
    db_session.add(drafted)
    await db_session.commit()

    fake_drive = FakeGoogleDriveClient(section_range=None)
    monkeypatch.setattr(decisions_module, "google_drive_client", fake_drive)

    resp = await ac.post(f"/decisions/{decision.id}/drive-draft/apply", follow_redirects=False)
    assert resp.status_code == 303

    await db_session.refresh(drafted)
    assert drafted.status == "failed"
    assert drafted.applied_at is None
    assert fake_drive.applied_calls == []

    entries = (
        await db_session.scalars(
            select(AuditLogEntry).where(
                AuditLogEntry.subject_id == decision.id,
                AuditLogEntry.event_type == "drive_doc_update_failed",
            )
        )
    ).all()
    assert len(entries) == 1
