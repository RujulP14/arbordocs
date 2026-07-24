from sqlalchemy import select

from app.db.models import GitHubInstallation, GoogleDriveInstallation, Project, RepoDocument, User
from app.pipeline.drive_index import sync_drive_index
from app.pipeline.github_index import sync_repo_index


class FakeGoogleDriveClient:
    """Deterministic fake Drive content client for tests — no real API calls.

    `docs` is the list of {"id", "name"} dicts `list_folder_docs` returns;
    `content_by_name` maps doc name -> flattened plain-text content for
    `get_doc_content`.
    """

    def __init__(self, docs: list[dict], content_by_name: dict[str, str]) -> None:
        self._docs = docs
        self._content_by_name = content_by_name
        self._docs_by_id = {d["id"]: d for d in docs}

    async def refresh_access_token(self, refresh_token: str) -> str:
        return "fake-access-token"

    async def list_folder_docs(self, access_token: str, folder_id: str) -> list[dict]:
        return self._docs

    async def get_doc_content(self, access_token: str, file_id: str) -> str:
        name = self._docs_by_id[file_id]["name"]
        return self._content_by_name[name]


class FakeGitHubClient:
    def __init__(self, tree: list[dict], files: dict[str, str]) -> None:
        self._tree = tree
        self._files = files

    async def get_repo_tree(self, installation_id: str, repo_full_name: str) -> list[dict]:
        return self._tree

    async def get_file_content(self, installation_id: str, repo_full_name: str, path: str) -> str:
        return self._files[path]


async def _make_project_with_drive_installation(db_session) -> Project:
    admin = User(github_login="octocat", is_admin=True)
    db_session.add(admin)
    await db_session.flush()
    project = Project(name="Test Project", created_by=admin.id)
    db_session.add(project)
    await db_session.flush()
    db_session.add(
        GoogleDriveInstallation(
            project_id=project.id,
            folder_id="folder-1",
            folder_name="Docs",
            refresh_token="refresh-token-1",
        )
    )
    await db_session.commit()
    return project


async def test_sync_drive_index_creates_drive_section_documents(db_session, fake_embedder):
    project = await _make_project_with_drive_installation(db_session)

    docs = [{"id": "doc-1", "name": "API Guidelines"}]
    content_by_name = {
        "API Guidelines": "# API Guidelines\n\nOverview text.\n\n## Pagination\n\nUse cursor pagination.\n"
    }
    client = FakeGoogleDriveClient(docs, content_by_name)

    documents = await sync_drive_index(db_session, project.id, client=client, embedder=fake_embedder)

    assert len(documents) == 2
    assert all(d.kind == "drive_section" for d in documents)
    assert all(d.path == "API Guidelines" for d in documents)
    anchors = {d.anchor for d in documents}
    assert anchors == {"api-guidelines", "pagination"}
    assert all(d.embedding is not None for d in documents)


async def test_sync_drive_index_resync_replaces_rather_than_duplicates(db_session, fake_embedder):
    project = await _make_project_with_drive_installation(db_session)
    docs = [{"id": "doc-1", "name": "Doc"}]
    content_by_name = {"Doc": "# Doc\n\nSome text.\n"}
    client = FakeGoogleDriveClient(docs, content_by_name)

    await sync_drive_index(db_session, project.id, client=client, embedder=fake_embedder)
    await sync_drive_index(db_session, project.id, client=client, embedder=fake_embedder)

    stored = (
        await db_session.scalars(select(RepoDocument).where(RepoDocument.project_id == project.id))
    ).all()
    assert len(stored) == 1


async def test_sync_drive_index_returns_empty_without_installation(db_session):
    admin = User(github_login="octocat", is_admin=True)
    db_session.add(admin)
    await db_session.flush()
    project = Project(name="No Drive Attached", created_by=admin.id)
    db_session.add(project)
    await db_session.commit()

    documents = await sync_drive_index(db_session, project.id, client=FakeGoogleDriveClient([], {}))

    assert documents == []


async def test_drive_resync_does_not_delete_github_sourced_rows(db_session, fake_embedder):
    """A real regression risk: both GitHub and Drive rows share the
    RepoDocument table — a Drive resync must never delete this project's
    GitHub-sourced rows, and vice versa (github_index.py's own delete is
    scoped the same way).
    """
    project = await _make_project_with_drive_installation(db_session)
    db_session.add(
        GitHubInstallation(project_id=project.id, installation_id="inst-1", repo_full_name="octo/repo")
    )
    await db_session.commit()

    github_client = FakeGitHubClient(
        tree=[{"path": "docs/api.md", "type": "blob", "size": 100}],
        files={"docs/api.md": "# API\n\nOverview.\n"},
    )
    await sync_repo_index(db_session, project.id, client=github_client, embedder=fake_embedder)

    drive_client = FakeGoogleDriveClient(
        docs=[{"id": "doc-1", "name": "Drive Doc"}],
        content_by_name={"Drive Doc": "# Drive Doc\n\nText.\n"},
    )
    await sync_drive_index(db_session, project.id, client=drive_client, embedder=fake_embedder)

    # Resync Drive again — GitHub rows must still be present afterward.
    await sync_drive_index(db_session, project.id, client=drive_client, embedder=fake_embedder)

    stored = (
        await db_session.scalars(select(RepoDocument).where(RepoDocument.project_id == project.id))
    ).all()
    kinds = {d.kind for d in stored}
    assert "doc_section" in kinds
    assert "drive_section" in kinds
    github_rows = [d for d in stored if d.kind == "doc_section"]
    assert len(github_rows) == 1
    drive_rows = [d for d in stored if d.kind == "drive_section"]
    assert len(drive_rows) == 1
