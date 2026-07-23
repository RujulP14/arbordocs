import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.pipeline.extraction as extraction_module
import app.pipeline.supersession as supersession_module
import app.worker.main as worker_main
from app.db.models import (
    AuditLogEntry,
    Candidate,
    Decision,
    DiscussionUnit,
    Message,
    Project,
    User,
)
from app.pipeline.audit import log_event


async def _make_project(db_session, github_login: str = "octocat") -> Project:
    admin = User(github_login=github_login, is_admin=True)
    db_session.add(admin)
    await db_session.flush()
    project = Project(name="Test Project", created_by=admin.id)
    db_session.add(project)
    await db_session.flush()
    return project


async def _audit_entries(db_session, subject_id) -> list[AuditLogEntry]:
    return (
        await db_session.scalars(
            select(AuditLogEntry)
            .where(AuditLogEntry.subject_id == subject_id)
            .order_by(AuditLogEntry.created_at)
        )
    ).all()


async def test_log_event_writes_a_row_with_correct_fields(db_session):
    project = await _make_project(db_session)
    subject_id = uuid.uuid4()

    entry = await log_event(
        db_session,
        project.id,
        "decision_extracted",
        "decision",
        subject_id,
        actor="octocat",
        payload={"statement": "use postgres"},
    )
    await db_session.commit()

    stored = await db_session.get(AuditLogEntry, entry.id)
    assert stored.project_id == project.id
    assert stored.event_type == "decision_extracted"
    assert stored.subject_type == "decision"
    assert stored.subject_id == subject_id
    assert stored.actor == "octocat"
    assert stored.payload == {"statement": "use postgres"}


async def test_log_event_defaults_actor_to_system(db_session):
    project = await _make_project(db_session)

    entry = await log_event(db_session, project.id, "unit_closed", "discussion_unit", uuid.uuid4())
    await db_session.commit()

    stored = await db_session.get(AuditLogEntry, entry.id)
    assert stored.actor == "system"
    assert stored.payload == {}


async def _patch_worker_session(monkeypatch, db_session):
    """Worker functions each open their own `async_session()` internally —
    point that at the same in-memory engine `db_session` uses, so the
    real worker functions can be exercised end-to-end in tests.
    """
    session_maker = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(worker_main, "async_session", session_maker)


async def test_close_due_units_logs_unit_closed(db_session, monkeypatch):
    await _patch_worker_session(monkeypatch, db_session)
    project = await _make_project(db_session)
    unit = DiscussionUnit(
        project_id=project.id,
        channel_id="chan-1",
        status="open",
        signal_close_requested=True,
        last_message_at=datetime.now(UTC),
    )
    db_session.add(unit)
    await db_session.commit()

    closed = await worker_main.close_due_units()

    assert len(closed) == 1
    entries = await _audit_entries(db_session, unit.id)
    assert len(entries) == 1
    assert entries[0].event_type == "unit_closed"
    assert entries[0].subject_type == "discussion_unit"
    assert entries[0].payload == {"close_reason": "signal"}


async def test_run_candidate_filter_logs_candidate_flagged(db_session, monkeypatch):
    await _patch_worker_session(monkeypatch, db_session)
    project = await _make_project(db_session)
    unit = DiscussionUnit(project_id=project.id, channel_id="chan-1", status="closed")
    db_session.add(unit)
    await db_session.flush()
    db_session.add(
        Message(
            project_id=project.id,
            discussion_unit_id=unit.id,
            channel_id="chan-1",
            discord_message_id="msg-1",
            author_id="user-1",
            content="let's go with the new plan",
            created_at=datetime.now(UTC),
            reactions=[],
        )
    )
    await db_session.commit()

    candidates = await worker_main.run_candidate_filter([unit])

    assert len(candidates) == 1
    entries = await _audit_entries(db_session, candidates[0].id)
    assert len(entries) == 1
    assert entries[0].event_type == "candidate_flagged"
    assert entries[0].subject_type == "candidate"
    assert "let's go with" in entries[0].payload["matched_keywords"]


async def test_run_candidate_filter_logs_nothing_on_no_signal(db_session, monkeypatch):
    await _patch_worker_session(monkeypatch, db_session)
    project = await _make_project(db_session)
    unit = DiscussionUnit(project_id=project.id, channel_id="chan-1", status="closed")
    db_session.add(unit)
    await db_session.flush()
    db_session.add(
        Message(
            project_id=project.id,
            discussion_unit_id=unit.id,
            channel_id="chan-1",
            discord_message_id="msg-1",
            author_id="user-1",
            content="just chatting about the weather",
            created_at=datetime.now(UTC),
            reactions=[],
        )
    )
    await db_session.commit()

    candidates = await worker_main.run_candidate_filter([unit])

    assert candidates == []
    all_entries = (await db_session.scalars(select(AuditLogEntry))).all()
    assert all_entries == []


async def test_run_extraction_logs_decision_extracted(db_session, monkeypatch, fake_groq_client):
    await _patch_worker_session(monkeypatch, db_session)
    project = await _make_project(db_session)
    unit = DiscussionUnit(
        project_id=project.id, channel_id="chan-1", status="closed", participant_ids=["user-1"]
    )
    db_session.add(unit)
    await db_session.flush()
    db_session.add(
        Message(
            project_id=project.id,
            discussion_unit_id=unit.id,
            channel_id="chan-1",
            discord_message_id="msg-1",
            author_id="user-1",
            content="we decided to use postgres",
            created_at=datetime.now(UTC),
            reactions=[],
        )
    )
    candidate = Candidate(project_id=project.id, discussion_unit_id=unit.id, score=1.0)
    db_session.add(candidate)
    await db_session.commit()

    client = fake_groq_client(
        [
            {
                "resolved": True,
                "statement": "Use postgres for the database",
                "type": "technical",
                "scope": "",
                "rationale": "",
                "decider": "",
                "message_ids": ["msg-1"],
                "confidence": 0.9,
            }
        ]
    )
    monkeypatch.setitem(
        extraction_module._PROVIDER_CALLERS, "groq", (extraction_module._call_groq, lambda: client)
    )

    decisions = await worker_main.run_extraction([candidate])

    assert len(decisions) == 1
    entries = await _audit_entries(db_session, decisions[0].id)
    assert len(entries) == 1
    assert entries[0].event_type == "decision_extracted"
    assert entries[0].payload["statement"] == "Use postgres for the database"


async def test_run_extraction_logs_decision_gated_out(db_session, monkeypatch, fake_groq_client):
    await _patch_worker_session(monkeypatch, db_session)
    project = await _make_project(db_session)
    unit = DiscussionUnit(
        project_id=project.id, channel_id="chan-1", status="closed", participant_ids=["user-1"]
    )
    db_session.add(unit)
    await db_session.flush()
    db_session.add(
        Message(
            project_id=project.id,
            discussion_unit_id=unit.id,
            channel_id="chan-1",
            discord_message_id="msg-1",
            author_id="user-1",
            content="lol final decision: pineapple pizza",
            created_at=datetime.now(UTC),
            reactions=[],
        )
    )
    candidate = Candidate(project_id=project.id, discussion_unit_id=unit.id, score=1.0)
    db_session.add(candidate)
    await db_session.commit()

    client = fake_groq_client(
        [
            {
                "resolved": False,
                "statement": "",
                "type": "technical",
                "scope": "",
                "rationale": "",
                "decider": "",
                "message_ids": [],
                "confidence": 0.0,
            }
        ]
    )
    monkeypatch.setitem(
        extraction_module._PROVIDER_CALLERS, "groq", (extraction_module._call_groq, lambda: client)
    )

    decisions = await worker_main.run_extraction([candidate])

    assert decisions == []
    entries = await _audit_entries(db_session, candidate.id)
    assert len(entries) == 1
    assert entries[0].event_type == "decision_gated_out"
    assert entries[0].subject_type == "candidate"


def _decision(project_id, **overrides) -> Decision:
    defaults = dict(
        project_id=project_id,
        candidate_id=uuid.uuid4(),
        statement="placeholder decision",
        statement_embedding=[0.0] * 384,
        type="technical",
        channel_id="chan-1",
        timestamp=datetime.now(UTC),
        authority_tier="medium",
        status="active",
        confidence=0.9,
    )
    defaults.update(overrides)
    return Decision(**defaults)


async def test_run_supersession_logs_classification(db_session, monkeypatch, fake_groq_client):
    await _patch_worker_session(monkeypatch, db_session)
    project = await _make_project(db_session)
    embedding = [1.0] + [0.0] * 383

    old_decision = _decision(
        project.id, statement="Use offset-based pagination", statement_embedding=embedding
    )
    db_session.add(old_decision)
    await db_session.commit()

    new_decision = _decision(
        project.id, statement="Use cursor-based pagination instead", statement_embedding=embedding
    )
    db_session.add(new_decision)
    await db_session.commit()

    client = fake_groq_client([{"relationship": "reversal", "confidence": 0.95}])
    monkeypatch.setitem(
        supersession_module._PROVIDER_CALLERS, "groq", (supersession_module._call_groq, lambda: client)
    )

    await worker_main.run_supersession([new_decision])

    entries = await _audit_entries(db_session, new_decision.id)
    assert len(entries) == 1
    assert entries[0].event_type == "supersession_classified"
    assert entries[0].payload["relationship"] == "reversal"
    assert entries[0].payload["existing_decision_id"] == str(old_decision.id)


async def test_run_reconciliation_logs_computation(db_session, monkeypatch):
    await _patch_worker_session(monkeypatch, db_session)
    project = await _make_project(db_session)
    embedding = [1.0] + [0.0] * 383

    decision = _decision(project.id, scope="backend/api", statement_embedding=embedding)
    db_session.add(decision)
    await db_session.commit()

    from app.db.models import RepoDocument

    doc = RepoDocument(
        project_id=project.id,
        kind="doc_section",
        path="docs/api.md",
        anchor="pagination",
        content="pagination docs",
        embedding=embedding,
    )
    db_session.add(doc)
    await db_session.commit()

    await worker_main.run_reconciliation([decision])

    entries = await _audit_entries(db_session, decision.id)
    assert len(entries) == 1
    assert entries[0].event_type == "reconciliation_computed"
    assert entries[0].payload["state"] == "unverified"
    assert "docs/api.md#pagination" in entries[0].payload["related_docs"]


async def test_run_reconciliation_logs_nothing_when_no_reconciliation(db_session, monkeypatch):
    await _patch_worker_session(monkeypatch, db_session)
    project = await _make_project(db_session)
    decision = _decision(project.id, scope=None)
    db_session.add(decision)
    await db_session.commit()

    await worker_main.run_reconciliation([decision])

    entries = await _audit_entries(db_session, decision.id)
    assert entries == []
