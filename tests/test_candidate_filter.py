from datetime import UTC, datetime

from app.db.models import DiscussionUnit, Message, Project, User
from app.pipeline.candidate_filter import score_unit


async def _make_project_and_unit(db_session) -> tuple[Project, DiscussionUnit]:
    admin = User(github_login="octocat", is_admin=True)
    db_session.add(admin)
    await db_session.flush()
    project = Project(name="Test Project", created_by=admin.id)
    db_session.add(project)
    await db_session.flush()
    unit = DiscussionUnit(project_id=project.id, channel_id="chan-1", status="closed")
    db_session.add(unit)
    await db_session.flush()
    return project, unit


def _message(project_id, unit_id, **overrides) -> Message:
    defaults = dict(
        project_id=project_id,
        discussion_unit_id=unit_id,
        channel_id="chan-1",
        discord_message_id=overrides.pop("discord_message_id", "msg-1"),
        author_id="user-1",
        content="hello",
        created_at=datetime.now(UTC),
        reactions=[],
    )
    defaults.update(overrides)
    return Message(**defaults)


async def test_keyword_match_flags_candidate(db_session, fake_embedder):
    project, unit = await _make_project_and_unit(db_session)
    db_session.add(_message(project.id, unit.id, content="ok let's go with the new plan"))
    await db_session.commit()

    candidate = await score_unit(db_session, unit, embedder=fake_embedder)

    assert candidate is not None
    assert "let's go with" in candidate.matched_keywords


async def test_reaction_signal_flags_candidate(db_session, fake_embedder):
    project, unit = await _make_project_and_unit(db_session)
    db_session.add(
        _message(
            project.id,
            unit.id,
            content="just some chatter, nothing special",
            reactions=[{"emoji": "✅", "count": 1}],
        )
    )
    await db_session.commit()

    candidate = await score_unit(db_session, unit, embedder=fake_embedder)

    assert candidate is not None
    assert candidate.reaction_signal is True
    assert candidate.matched_keywords == []


async def test_embedding_similarity_to_exemplar_flags_candidate(db_session, fake_embedder):
    project, unit = await _make_project_and_unit(db_session)
    msg = _message(project.id, unit.id, content="postgres discussion")
    msg.embedding = fake_embedder.embed("postgres discussion")
    db_session.add(msg)
    await db_session.commit()

    candidate = await score_unit(db_session, unit, embedder=fake_embedder)

    assert candidate is not None
    assert candidate.embedding_score > 0


async def test_no_signal_returns_none(db_session, fake_embedder):
    project, unit = await _make_project_and_unit(db_session)
    db_session.add(_message(project.id, unit.id, content="just chatting about the weather"))
    await db_session.commit()

    candidate = await score_unit(db_session, unit, embedder=fake_embedder)

    assert candidate is None


async def test_empty_unit_returns_none(db_session, fake_embedder):
    project, unit = await _make_project_and_unit(db_session)
    await db_session.commit()

    candidate = await score_unit(db_session, unit, embedder=fake_embedder)

    assert candidate is None
