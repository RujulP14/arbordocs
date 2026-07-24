from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GoogleDriveInstallation, RepoDocument
from app.ingestion.google.client import google_drive_client
from app.pipeline.embeddings import get_embedder
from app.pipeline.github_index import parse_doc_sections


async def sync_drive_index(db: AsyncSession, project_id, client=None, embedder=None) -> list[RepoDocument]:
    """Issue #14, piece 1: list the connected Drive folder's Google Docs,
    fetch and flatten each into markdown-heading text, parse into sections
    (reusing github_index.py's parse_doc_sections as-is — it's plain
    heading-based chunking, not GitHub-specific), embed every chunk, and
    replace this project's `kind="drive_section"` rows wholesale (mirrors
    sync_repo_index's replace-not-diff approach, scoped by kind so a Drive
    resync never touches this project's GitHub-sourced rows).

    Returns the list of newly-created RepoDocument rows. Returns an empty
    list without any Drive calls if the project has no
    GoogleDriveInstallation.
    """
    client = client or google_drive_client
    embedder = embedder or get_embedder()

    installation = await db.scalar(
        select(GoogleDriveInstallation).where(GoogleDriveInstallation.project_id == project_id)
    )
    if installation is None:
        return []

    access_token = await client.refresh_access_token(installation.refresh_token)
    docs = await client.list_folder_docs(access_token, installation.folder_id)

    chunks = []
    for doc in docs:
        content = await client.get_doc_content(access_token, doc["id"])
        chunks.extend(parse_doc_sections(doc["name"], content))

    await db.execute(
        delete(RepoDocument).where(
            RepoDocument.project_id == project_id,
            RepoDocument.kind == "drive_section",
        )
    )

    documents = []
    for chunk in chunks:
        chunk["kind"] = "drive_section"
        document = RepoDocument(
            project_id=project_id,
            embedding=embedder.embed(chunk["content"]),
            **chunk,
        )
        db.add(document)
        documents.append(document)

    await db.flush()
    return documents
