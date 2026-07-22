from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Decision, RepoDocument
from app.pipeline.embeddings import cosine_similarity


async def find_related_repo_documents(
    db: AsyncSession, project_id, embedding: list[float]
) -> list[tuple[RepoDocument, float]]:
    """Retrieve step (SPEC.md §4, tier-b): repo documents in the project
    with an embedding above settings.reconciliation_similarity_threshold,
    sorted by similarity descending.

    Scored in Python (not a DB-side pgvector query) so this works identically
    against real Postgres+pgvector and the in-memory sqlite used by tests
    (sqlite has no vector ops) — the same tradeoff already made by Stage 0/1/3
    (app/pipeline/reconstruction.py, candidate_filter.py, supersession.py).
    """
    documents = (
        await db.scalars(
            select(RepoDocument).where(
                RepoDocument.project_id == project_id,
                RepoDocument.embedding.is_not(None),
            )
        )
    ).all()

    scored = [(doc, cosine_similarity(embedding, doc.embedding)) for doc in documents]
    scored = [(doc, score) for doc, score in scored if score >= settings.reconciliation_similarity_threshold]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored


async def reconcile_decision(db: AsyncSession, decision: Decision) -> dict | None:
    """SPEC.md §4 (tier-b): surface repo docs/code related to a decision by
    embedding similarity. Returns None without modifying the decision when:
    - decision.scope is None (no reconcilable scope per SPEC.md §4's framing)
    - decision.statement_embedding is None (no embedding to search with)
    - the project has zero RepoDocument rows (repo not yet connected/synced)

    Otherwise writes a reconciliation dict to decision.reconciliation and
    returns it for caller logging. `state` is always "unverified" in v1 —
    tier-a (concrete contradiction detection, the only path to "consistent"/
    "contradiction") is deferred to Phase 6.
    """
    if decision.scope is None or decision.statement_embedding is None:
        return None

    repo_doc_count = await db.scalar(
        select(func.count()).where(RepoDocument.project_id == decision.project_id)
    )
    if not repo_doc_count:
        return None

    related = await find_related_repo_documents(db, decision.project_id, decision.statement_embedding)

    cap = settings.reconciliation_max_related
    related_code = [f"{doc.path}#{doc.anchor}" for doc, _ in related if doc.kind == "code_symbol"][:cap]
    related_docs = [f"{doc.path}#{doc.anchor}" for doc, _ in related if doc.kind == "doc_section"][:cap]

    reconciliation = {
        "state": "unverified",
        "related_code": related_code,
        "related_docs": related_docs,
        "notes": None,
    }
    decision.reconciliation = reconciliation
    return reconciliation
