import uuid
from datetime import UTC, datetime

from app.db.models import Decision, Project, User
from app.pipeline.supersession import classify_relationship, find_similar_active_decisions


async def _make_project(db_session) -> Project:
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


async def test_retrieval_only_returns_active_decisions_above_threshold(db_session):
    project = await _make_project(db_session)

    similar = _decision(project.id, statement="similar", statement_embedding=[1.0] + [0.0] * 383)
    dissimilar = _decision(project.id, statement="dissimilar", statement_embedding=[0.0, 1.0] + [0.0] * 382)
    superseded = _decision(
        project.id, statement="old", statement_embedding=[1.0] + [0.0] * 383, status="superseded"
    )
    db_session.add_all([similar, dissimilar, superseded])
    await db_session.commit()

    new_embedding = [1.0] + [0.0] * 383  # identical to `similar`
    results = await find_similar_active_decisions(db_session, project.id, new_embedding, uuid.uuid4())

    result_ids = [d.id for d, _score in results]
    assert similar.id in result_ids
    assert dissimilar.id not in result_ids  # orthogonal vector, similarity 0 < threshold
    assert superseded.id not in result_ids  # not active, excluded regardless of similarity


async def test_retrieval_excludes_the_new_decisions_own_row(db_session):
    project = await _make_project(db_session)
    embedding = [1.0] + [0.0] * 383
    new_decision = _decision(project.id, statement="new", statement_embedding=embedding)
    db_session.add(new_decision)
    await db_session.commit()

    results = await find_similar_active_decisions(db_session, project.id, embedding, new_decision.id)

    assert new_decision.id not in [d.id for d, _score in results]


async def test_reversal_marks_existing_superseded_and_links_chain(db_session, fake_groq_client):
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

    classifications = await classify_relationship(db_session, new_decision, client=client, provider="groq")

    assert len(classifications) == 1
    assert classifications[0]["relationship"] == "reversal"
    assert classifications[0]["existing_decision_id"] == old_decision.id

    assert old_decision.status == "superseded"
    assert old_decision.superseded_by == new_decision.id
    assert new_decision.supersedes == old_decision.id


async def test_unrelated_leaves_both_decisions_untouched(db_session, fake_groq_client):
    project = await _make_project(db_session)
    embedding = [1.0] + [0.0] * 383

    old_decision = _decision(
        project.id, statement="Use Postgres for the database", statement_embedding=embedding
    )
    db_session.add(old_decision)
    await db_session.commit()

    new_decision = _decision(project.id, statement="Standup moves to Fridays", statement_embedding=embedding)
    db_session.add(new_decision)
    await db_session.commit()

    client = fake_groq_client([{"relationship": "unrelated", "confidence": 0.9}])

    await classify_relationship(db_session, new_decision, client=client, provider="groq")

    assert old_decision.status == "active"
    assert old_decision.superseded_by is None
    assert new_decision.supersedes is None


async def test_duplicate_also_marks_existing_superseded(db_session, fake_groq_client):
    project = await _make_project(db_session)
    embedding = [1.0] + [0.0] * 383

    old_decision = _decision(project.id, statement="Standup moves to Fridays", statement_embedding=embedding)
    db_session.add(old_decision)
    await db_session.commit()

    new_decision = _decision(
        project.id, statement="Just a reminder, standup is Fridays now", statement_embedding=embedding
    )
    db_session.add(new_decision)
    await db_session.commit()

    client = fake_groq_client([{"relationship": "duplicate", "confidence": 0.85}])

    await classify_relationship(db_session, new_decision, client=client, provider="groq")

    assert old_decision.status == "superseded"
    assert old_decision.superseded_by == new_decision.id


async def test_no_similar_decisions_returns_empty_list_without_calling_llm(db_session, fake_groq_client):
    project = await _make_project(db_session)
    new_decision = _decision(
        project.id, statement="Only decision so far", statement_embedding=[1.0] + [0.0] * 383
    )
    db_session.add(new_decision)
    await db_session.commit()

    client = fake_groq_client([])  # no canned responses — would raise IndexError if called

    classifications = await classify_relationship(db_session, new_decision, client=client, provider="groq")

    assert classifications == []
