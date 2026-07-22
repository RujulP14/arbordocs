from sqlalchemy import select

from app.db.models import GitHubInstallation, Project, RepoDocument, User
from app.pipeline.github_index import parse_code_symbols, parse_doc_sections, sync_repo_index


def test_parse_doc_sections_splits_by_heading_with_correct_anchors():
    content = "# Title\n\nIntro text.\n\n## Section One\n\nSome content here.\n\n## Section Two\n\nMore.\n"

    sections = parse_doc_sections("docs/test.md", content)

    assert [s["anchor"] for s in sections] == ["title", "section-one", "section-two"]
    assert all(s["kind"] == "doc_section" for s in sections)
    assert all(s["path"] == "docs/test.md" for s in sections)
    assert all(s["symbol_name"] is None for s in sections)
    assert "Some content here." in sections[1]["content"]


def test_parse_doc_sections_returns_empty_for_headingless_file():
    assert parse_doc_sections("docs/no-headings.md", "just plain text, no headings at all\n") == []


def test_parse_code_symbols_extracts_functions_classes_and_methods():
    content = (
        "def foo(x):\n"
        "    return x + 1\n"
        "\n\n"
        "class Bar:\n"
        "    def method_a(self):\n"
        "        pass\n"
        "\n"
        "    async def method_b(self):\n"
        "        pass\n"
    )

    symbols = parse_code_symbols("app/test.py", content)

    names = [s["symbol_name"] for s in symbols]
    assert names == ["foo", "Bar", "Bar.method_a", "Bar.method_b"]
    assert all(s["kind"] == "code_symbol" for s in symbols)
    assert all(s["path"] == "app/test.py" for s in symbols)
    foo = symbols[0]
    assert foo["anchor"] == "foo"
    assert foo["line_start"] == 1
    assert foo["line_end"] == 2


def test_parse_code_symbols_returns_empty_for_invalid_python():
    assert parse_code_symbols("app/broken.py", "def foo(:\n    pass\n") == []


class FakeGitHubClient:
    """Deterministic fake GitHub content client for tests — no real API calls.

    `tree` is the list of tree entries `get_repo_tree` returns; `files` maps
    path -> file content for `get_file_content`.
    """

    def __init__(self, tree: list[dict], files: dict[str, str]) -> None:
        self._tree = tree
        self._files = files

    async def get_repo_tree(self, installation_id: str, repo_full_name: str) -> list[dict]:
        return self._tree

    async def get_file_content(self, installation_id: str, repo_full_name: str, path: str) -> str:
        return self._files[path]


async def _make_project_with_installation(db_session) -> Project:
    admin = User(github_login="octocat", is_admin=True)
    db_session.add(admin)
    await db_session.flush()
    project = Project(name="Test Project", created_by=admin.id)
    db_session.add(project)
    await db_session.flush()
    db_session.add(
        GitHubInstallation(project_id=project.id, installation_id="inst-1", repo_full_name="octo/repo")
    )
    await db_session.commit()
    return project


async def test_sync_repo_index_creates_documents_from_docs_and_code(db_session, fake_embedder):
    project = await _make_project_with_installation(db_session)

    tree = [
        {"path": "docs/api.md", "type": "blob", "size": 100},
        {"path": "app/util.py", "type": "blob", "size": 100},
        {"path": "image.png", "type": "blob", "size": 100},  # not .md/.py — skipped
        {"path": "docs/subdir", "type": "tree", "size": 0},  # a directory — skipped
    ]
    files = {
        "docs/api.md": "# API\n\nOverview text.\n",
        "app/util.py": "def helper():\n    return 1\n",
    }
    client = FakeGitHubClient(tree, files)

    documents = await sync_repo_index(db_session, project.id, client=client, embedder=fake_embedder)

    assert len(documents) == 2
    kinds = {d.path: d.kind for d in documents}
    assert kinds["docs/api.md"] == "doc_section"
    assert kinds["app/util.py"] == "code_symbol"
    assert all(d.embedding is not None for d in documents)


async def test_sync_repo_index_skips_files_over_size_cap(db_session, fake_embedder, monkeypatch):
    project = await _make_project_with_installation(db_session)
    monkeypatch.setattr("app.pipeline.github_index.settings.github_sync_max_file_size_bytes", 50)

    tree = [
        {"path": "docs/small.md", "type": "blob", "size": 10},
        {"path": "docs/big.md", "type": "blob", "size": 999},
    ]
    files = {"docs/small.md": "# Small\n\ntext\n", "docs/big.md": "# Big\n\ntext\n"}
    client = FakeGitHubClient(tree, files)

    documents = await sync_repo_index(db_session, project.id, client=client, embedder=fake_embedder)

    assert {d.path for d in documents} == {"docs/small.md"}


async def test_sync_repo_index_resync_replaces_rather_than_duplicates(db_session, fake_embedder):
    project = await _make_project_with_installation(db_session)
    tree = [{"path": "docs/api.md", "type": "blob", "size": 100}]
    files = {"docs/api.md": "# API\n\nOverview text.\n"}
    client = FakeGitHubClient(tree, files)

    await sync_repo_index(db_session, project.id, client=client, embedder=fake_embedder)
    await sync_repo_index(db_session, project.id, client=client, embedder=fake_embedder)

    stored = (
        await db_session.scalars(select(RepoDocument).where(RepoDocument.project_id == project.id))
    ).all()
    assert len(stored) == 1


async def test_sync_repo_index_returns_empty_without_installation(db_session):
    admin = User(github_login="octocat", is_admin=True)
    db_session.add(admin)
    await db_session.flush()
    project = Project(name="No Repo Attached", created_by=admin.id)
    db_session.add(project)
    await db_session.commit()

    documents = await sync_repo_index(db_session, project.id, client=FakeGitHubClient([], {}))

    assert documents == []
