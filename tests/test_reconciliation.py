import uuid
from datetime import UTC, datetime

from app.db.models import Decision, Project, RepoDocument, User
from app.pipeline.reconciliation import find_related_repo_documents, reconcile_decision


async def _make_project(db_session, github_login: str = "octocat") -> Project:
    admin = User(github_login=github_login, is_admin=True)
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
        scope="backend/api",
        type="technical",
        channel_id="chan-1",
        timestamp=datetime.now(UTC),
        authority_tier="medium",
        status="active",
        confidence=0.9,
    )
    defaults.update(overrides)
    return Decision(**defaults)


def _repo_document(project_id, **overrides) -> RepoDocument:
    defaults = dict(
        project_id=project_id,
        kind="doc_section",
        path="docs/api.md",
        symbol_name=None,
        anchor="pagination",
        content="placeholder content",
        embedding=[0.0] * 384,
    )
    defaults.update(overrides)
    return RepoDocument(**defaults)


async def test_retrieval_only_returns_documents_above_threshold(db_session):
    project = await _make_project(db_session)

    similar = _repo_document(project.id, path="docs/api.md", embedding=[1.0] + [0.0] * 383)
    dissimilar = _repo_document(project.id, path="docs/other.md", embedding=[0.0, 1.0] + [0.0] * 382)
    db_session.add_all([similar, dissimilar])
    await db_session.commit()

    embedding = [1.0] + [0.0] * 383  # identical to `similar`
    results = await find_related_repo_documents(db_session, project.id, embedding)

    result_ids = [doc.id for doc, _score in results]
    assert similar.id in result_ids
    assert dissimilar.id not in result_ids  # orthogonal vector, similarity 0 < threshold


async def test_retrieval_scoped_to_project(db_session):
    project_a = await _make_project(db_session, github_login="octocat-a")
    project_b = await _make_project(db_session, github_login="octocat-b")
    embedding = [1.0] + [0.0] * 383

    doc_a = _repo_document(project_a.id, embedding=embedding)
    doc_b = _repo_document(project_b.id, embedding=embedding)
    db_session.add_all([doc_a, doc_b])
    await db_session.commit()

    results = await find_related_repo_documents(db_session, project_a.id, embedding)

    result_ids = [doc.id for doc, _score in results]
    assert doc_a.id in result_ids
    assert doc_b.id not in result_ids


async def test_reconcile_returns_none_without_scope(db_session):
    project = await _make_project(db_session)
    decision = _decision(project.id, scope=None)
    db_session.add(decision)
    await db_session.commit()

    result = await reconcile_decision(db_session, decision)

    assert result is None
    assert decision.reconciliation is None


async def test_reconcile_returns_none_without_statement_embedding(db_session):
    project = await _make_project(db_session)
    decision = _decision(project.id, statement_embedding=None)
    db_session.add(decision)
    await db_session.commit()

    result = await reconcile_decision(db_session, decision)

    assert result is None
    assert decision.reconciliation is None


async def test_reconcile_returns_none_without_any_repo_documents(db_session):
    project = await _make_project(db_session)
    decision = _decision(project.id)
    db_session.add(decision)
    await db_session.commit()

    result = await reconcile_decision(db_session, decision)

    assert result is None
    assert decision.reconciliation is None


async def test_reconcile_splits_related_code_and_docs_with_correct_anchors(db_session):
    project = await _make_project(db_session)
    embedding = [1.0] + [0.0] * 383

    decision = _decision(project.id, statement_embedding=embedding)
    doc_section = _repo_document(
        project.id, kind="doc_section", path="docs/api.md", anchor="pagination", embedding=embedding
    )
    code_symbol = _repo_document(
        project.id,
        kind="code_symbol",
        path="app/routes.py",
        symbol_name="list_users",
        anchor="list_users",
        embedding=embedding,
    )
    db_session.add_all([decision, doc_section, code_symbol])
    await db_session.commit()

    result = await reconcile_decision(db_session, decision)

    assert result["state"] == "unverified"
    assert result["related_docs"] == ["docs/api.md#pagination"]
    assert result["related_code"] == ["app/routes.py#list_users"]
    assert decision.reconciliation == result


async def test_reconcile_caps_related_lists_at_max_related(db_session, monkeypatch):
    monkeypatch.setattr("app.pipeline.reconciliation.settings.reconciliation_max_related", 2)
    project = await _make_project(db_session)
    embedding = [1.0] + [0.0] * 383

    decision = _decision(project.id, statement_embedding=embedding)
    docs = [
        _repo_document(project.id, path=f"docs/section{i}.md", anchor=f"section-{i}", embedding=embedding)
        for i in range(4)
    ]
    db_session.add(decision)
    db_session.add_all(docs)
    await db_session.commit()

    result = await reconcile_decision(db_session, decision)

    assert len(result["related_docs"]) == 2
