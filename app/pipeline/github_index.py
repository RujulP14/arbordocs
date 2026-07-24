import ast
import re

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import GitHubInstallation, RepoDocument
from app.ingestion.github.client import github_app_client
from app.pipeline.embeddings import get_embedder

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_SLUG_STRIP_RE = re.compile(r"[^\w\s-]")
_SLUG_SPACE_RE = re.compile(r"[\s]+")


def _slugify(heading_text: str) -> str:
    """GitHub-style heading anchor slug: lowercase, strip punctuation, spaces to hyphens."""
    slug = _SLUG_STRIP_RE.sub("", heading_text.lower())
    return _SLUG_SPACE_RE.sub("-", slug.strip())


def parse_doc_sections(path: str, content: str) -> list[dict]:
    """Split a markdown file into sections by heading (SPEC.md §4: "Parse
    docs ... into sections"). Each section runs from one heading line to the
    next (of any level) or end of file. Anchors are GitHub-style heading
    slugs, matching the `"docs/api.md#pagination"` reference format from
    SPEC.md §6.
    """
    matches = list(HEADING_RE.finditer(content))
    if not matches:
        return []

    sections = []
    for i, match in enumerate(matches):
        heading_text = match.group(2)
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        section_text = content[start:end].strip()
        line_start = content.count("\n", 0, start) + 1

        sections.append(
            {
                "kind": "doc_section",
                "path": path,
                "symbol_name": None,
                "anchor": _slugify(heading_text),
                "content": section_text,
                "line_start": line_start,
                "line_end": line_start + section_text.count("\n"),
            }
        )
    return sections


def parse_code_symbols(path: str, content: str) -> list[dict]:
    """Extract top-level functions/classes and class methods from a Python
    file via stdlib `ast` (SPEC.md §9: "AST via Python ast for v1" —
    tree-sitter is the explicitly deferred language-agnostic upgrade, so
    non-Python files aren't parsed for code symbols in this pass).
    """
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    symbols = []

    def _add_symbol(node: ast.AST, name: str) -> None:
        segment = ast.get_source_segment(content, node)
        if segment is None:
            return
        symbols.append(
            {
                "kind": "code_symbol",
                "path": path,
                "symbol_name": name,
                "anchor": name,
                "content": segment,
                "line_start": node.lineno,
                "line_end": getattr(node, "end_lineno", node.lineno),
            }
        )

    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            _add_symbol(node, node.name)
        elif isinstance(node, ast.ClassDef):
            _add_symbol(node, node.name)
            for child in node.body:
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    _add_symbol(child, f"{node.name}.{child.name}")

    return symbols


def _select_paths(tree: list[dict]) -> list[str]:
    """Filter a repo tree to markdown + Python files under the configured
    size cap, capped at the configured max file count (SPEC.md §4's
    "lightweight per-project index" scope — full unbounded ingestion is
    explicitly out of scope).
    """
    selected = []
    for entry in tree:
        if entry.get("type") != "blob":
            continue
        path = entry["path"]
        if not (path.endswith(".md") or path.endswith(".py")):
            continue
        if entry.get("size", 0) > settings.github_sync_max_file_size_bytes:
            continue
        selected.append(path)
        if len(selected) >= settings.github_sync_max_files:
            break
    return selected


async def sync_repo_index(db: AsyncSession, project_id, client=None, embedder=None) -> list[RepoDocument]:
    """SPEC.md §4: list the installed repo's tree, fetch markdown/Python
    files under the configured caps, parse each into doc sections or code
    symbols, embed every chunk, and replace this project's existing
    `RepoDocument` rows wholesale (simplest correct approach for v1 — no
    incremental diffing).

    Returns the list of newly-created RepoDocument rows. Returns an empty
    list without any GitHub calls if the project has no GitHubInstallation.
    """
    client = client or github_app_client
    embedder = embedder or get_embedder()

    installation = await db.scalar(
        select(GitHubInstallation).where(GitHubInstallation.project_id == project_id)
    )
    if installation is None:
        return []

    tree = await client.get_repo_tree(installation.installation_id, installation.repo_full_name)
    paths = _select_paths(tree)

    chunks = []
    for path in paths:
        content = await client.get_file_content(
            installation.installation_id, installation.repo_full_name, path
        )
        if path.endswith(".md"):
            chunks.extend(parse_doc_sections(path, content))
        else:
            chunks.extend(parse_code_symbols(path, content))

    # Scoped by kind (issue #14) — a GitHub resync must never delete this
    # project's Drive-sourced rows, which share the same table.
    await db.execute(
        delete(RepoDocument).where(
            RepoDocument.project_id == project_id,
            RepoDocument.kind.in_(["doc_section", "code_symbol"]),
        )
    )

    documents = []
    for chunk in chunks:
        document = RepoDocument(
            project_id=project_id,
            embedding=embedder.embed(chunk["content"]),
            **chunk,
        )
        db.add(document)
        documents.append(document)

    await db.flush()
    return documents
