from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Candidate, DiscussionUnit, Message
from app.pipeline.embeddings import Embedder, cosine_similarity, get_embedder

# Cheap, high-recall keyword cues (SPEC.md §5, Stage 1) — over-flag freely,
# Stage 2's LLM gate (Phase 4) handles precision.
KEYWORD_PATTERNS = [
    # "let's (just/go ahead and) go/stick with X"
    "let's go with",
    "lets go with",
    "let's just go with",
    "lets just go with",
    "let's go ahead with",
    "lets go ahead with",
    "let's stick with",
    "lets stick with",
    "let's stay with",
    "lets stay with",
    # "we decided/agreed/settled (on/to) X"
    "we decided",
    "we've decided",
    "we've decided to",
    "we decided to",
    "we agreed",
    "we've agreed",
    "we agreed to",
    "agreed to go with",
    "we settled on",
    "we've settled on",
    "settled on",
    "we landed on",
    "we've landed on",
    "landed on",
    "we're settling on",
    # "going with / going to X"
    "going with",
    "we're going to",
    "we are going to",
    "we will go with",
    "we're going with",
    "we are going with",
    "going to go with",
    # "switching / moving to X"
    "switching to",
    "switch to",
    "moving to",
    "move to",
    "we're moving to",
    "we are moving to",
    # explicit decision/resolution framing
    "decision is to",
    "the decision is",
    "final call",
    "final decision",
    "the policy is",
    "policy is now",
    "the plan is to",
    "the call is to",
    "the takeaway is",
    "resolved:",
    "resolution:",
    # "we will/we're use/adopt/keep/drop X"
    "we will use",
    "we're using",
    "we will be using",
    "we'll use",
    "we'll be using",
    "we're adopting",
    "we will adopt",
    "we're dropping",
    "we will drop",
    "we're keeping",
    "we will keep",
    "we're picking",
    "we picked",
    "we chose",
    "we've chosen",
    "we're choosing",
    "opted for",
    "opting for",
    # temporal/durability framing
    "from now on",
    "going forward",
    "effective immediately",
]

# A handful of known-decision exemplars for embedding similarity, per spec.
EXEMPLAR_DECISIONS = [
    "We decided to use Postgres for the database.",
    "From now on, all API responses must be paginated by default.",
    "Final call: we're deprecating the v1 auth flow.",
    "Let's go with cursor-based pagination instead of offset.",
    "The policy is that all PRs require two approvals before merge.",
    "We decided to go with REST instead of GraphQL for the public API.",
    "Going with Python for this service, not Go.",
    "We'll use Postgres, not MySQL — transactions matter here.",
    "Switching to TypeScript for all new frontend code from now on.",
    "The team decided to use GitHub Actions instead of Jenkins.",
    "We're adopting trunk-based development going forward.",
    "We decided to drop support for IE11 in the next release.",
    "The call is to use JWT for auth, not session cookies.",
    "We agreed to keep the monorepo rather than splitting into microservices.",
    "We're going with the vendor's SDK, not writing our own integration.",
]

CHECK_MARK_EMOJI = "✅"


async def score_unit(
    db: AsyncSession,
    unit: DiscussionUnit,
    embedder: Embedder | None = None,
) -> Candidate | None:
    """Stage 1 (SPEC.md §5): score a closed discussion unit for decision-likeness.

    Flags a candidate on ANY signal (keyword OR embedding-vs-exemplar OR a
    checkmark reaction) — tuned for recall, not precision. Returns None if no
    signal fired at all (nothing to record).
    """
    embedder = embedder or get_embedder()
    messages = (
        await db.scalars(
            select(Message).where(Message.discussion_unit_id == unit.id).order_by(Message.created_at)
        )
    ).all()
    if not messages:
        return None

    full_text = " ".join(m.content for m in messages).lower()
    matched_keywords = [kw for kw in KEYWORD_PATTERNS if kw in full_text]

    embedding_score = 0.0
    for message in messages:
        if message.embedding is None:
            continue
        for exemplar in EXEMPLAR_DECISIONS:
            similarity = cosine_similarity(message.embedding, embedder.embed(exemplar))
            embedding_score = max(embedding_score, similarity)

    reaction_signal = any(r.get("emoji") == CHECK_MARK_EMOJI for m in messages for r in (m.reactions or []))

    embedding_hit = embedding_score >= settings.candidate_embedding_threshold
    if not (matched_keywords or embedding_hit or reaction_signal):
        return None

    score = max(
        1.0 if matched_keywords else 0.0,
        embedding_score if embedding_hit else 0.0,
        1.0 if reaction_signal else 0.0,
    )

    candidate = Candidate(
        project_id=unit.project_id,
        discussion_unit_id=unit.id,
        score=score,
        matched_keywords=matched_keywords,
        embedding_score=embedding_score,
        reaction_signal=reaction_signal,
    )
    db.add(candidate)
    return candidate
