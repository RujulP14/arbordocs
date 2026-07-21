from datetime import UTC, datetime, timedelta

from app.config import settings
from app.db.models import DiscussionUnit, Message, Project, User
from app.pipeline.reconstruction import assign_message_to_discussion_unit


async def _make_project(db_session) -> Project:
    admin = User(github_login="octocat", is_admin=True)
    db_session.add(admin)
    await db_session.flush()
    project = Project(name="Test Project", created_by=admin.id)
    db_session.add(project)
    await db_session.flush()
    return project


def _message(project_id, **overrides) -> Message:
    defaults = dict(
        project_id=project_id,
        channel_id="chan-1",
        discord_message_id=overrides.pop("discord_message_id", "msg-1"),
        author_id="user-1",
        content="hello",
        created_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return Message(**defaults)


async def test_new_unit_created_for_first_message(db_session, fake_embedder):
    project = await _make_project(db_session)
    msg = _message(project.id, content="unrelated chatter")
    db_session.add(msg)
    await db_session.flush()

    unit = await assign_message_to_discussion_unit(db_session, msg, embedder=fake_embedder)

    assert unit.status == "open"
    assert unit.participant_ids == ["user-1"]
    assert msg.discussion_unit_id == unit.id


async def test_reply_joins_parent_unit(db_session, fake_embedder):
    project = await _make_project(db_session)
    parent = _message(project.id, discord_message_id="msg-1", content="unrelated chatter")
    db_session.add(parent)
    await db_session.flush()
    parent_unit = await assign_message_to_discussion_unit(db_session, parent, embedder=fake_embedder)
    await db_session.commit()

    reply = _message(
        project.id,
        discord_message_id="msg-2",
        author_id="user-2",
        content="totally different topic, unrelated",
        reply_to_message_id="msg-1",
    )
    db_session.add(reply)
    await db_session.flush()
    reply_unit = await assign_message_to_discussion_unit(db_session, reply, embedder=fake_embedder)

    assert reply_unit.id == parent_unit.id
    assert "user-2" in reply_unit.participant_ids


async def test_temporal_cutoff_prevents_join(db_session, fake_embedder):
    project = await _make_project(db_session)
    old_time = datetime.now(UTC) - timedelta(minutes=settings.reconstruction_inactivity_minutes + 5)
    first = _message(project.id, discord_message_id="msg-1", content="unrelated", created_at=old_time)
    db_session.add(first)
    await db_session.flush()
    first_unit = await assign_message_to_discussion_unit(db_session, first, embedder=fake_embedder)
    await db_session.commit()

    second = _message(
        project.id,
        discord_message_id="msg-2",
        author_id="user-2",
        content="unrelated",
        created_at=datetime.now(UTC),
    )
    db_session.add(second)
    await db_session.flush()
    second_unit = await assign_message_to_discussion_unit(db_session, second, embedder=fake_embedder)

    assert second_unit.id != first_unit.id


async def test_participant_overlap_joins_unit(db_session, fake_embedder):
    project = await _make_project(db_session)
    first = _message(project.id, discord_message_id="msg-1", author_id="user-1", content="unrelated")
    db_session.add(first)
    await db_session.flush()
    first_unit = await assign_message_to_discussion_unit(db_session, first, embedder=fake_embedder)
    await db_session.commit()

    second = _message(
        project.id, discord_message_id="msg-2", author_id="user-1", content="something else entirely"
    )
    db_session.add(second)
    await db_session.flush()
    second_unit = await assign_message_to_discussion_unit(db_session, second, embedder=fake_embedder)

    assert second_unit.id == first_unit.id


async def test_embedding_similarity_joins_unit(db_session, fake_embedder):
    project = await _make_project(db_session)
    first = _message(project.id, discord_message_id="msg-1", author_id="user-1", content="let's use postgres")
    db_session.add(first)
    await db_session.flush()
    first_unit = await assign_message_to_discussion_unit(db_session, first, embedder=fake_embedder)
    await db_session.commit()

    second = _message(
        project.id,
        discord_message_id="msg-2",
        author_id="user-2",
        content="agreed, postgres is the way to go",
    )
    db_session.add(second)
    await db_session.flush()
    second_unit = await assign_message_to_discussion_unit(db_session, second, embedder=fake_embedder)

    assert second_unit.id == first_unit.id


async def test_no_similarity_and_no_overlap_opens_new_unit(db_session, fake_embedder):
    project = await _make_project(db_session)
    first = _message(project.id, discord_message_id="msg-1", author_id="user-1", content="let's use postgres")
    db_session.add(first)
    await db_session.flush()
    first_unit = await assign_message_to_discussion_unit(db_session, first, embedder=fake_embedder)
    await db_session.commit()

    second = _message(
        project.id,
        discord_message_id="msg-2",
        author_id="user-2",
        content="unrelated topic about pagination",
    )
    db_session.add(second)
    await db_session.flush()
    second_unit = await assign_message_to_discussion_unit(db_session, second, embedder=fake_embedder)

    assert second_unit.id != first_unit.id


async def test_closed_unit_is_not_joined(db_session, fake_embedder):
    project = await _make_project(db_session)
    first = _message(project.id, discord_message_id="msg-1", author_id="user-1", content="unrelated")
    db_session.add(first)
    await db_session.flush()
    first_unit = await assign_message_to_discussion_unit(db_session, first, embedder=fake_embedder)
    first_unit.status = "closed"
    await db_session.commit()

    second = _message(project.id, discord_message_id="msg-2", author_id="user-1", content="unrelated")
    db_session.add(second)
    await db_session.flush()
    second_unit = await assign_message_to_discussion_unit(db_session, second, embedder=fake_embedder)

    assert second_unit.id != first_unit.id
    all_units = (await db_session.execute(DiscussionUnit.__table__.select())).mappings().all()
    assert len(all_units) == 2
