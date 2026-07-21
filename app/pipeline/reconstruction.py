from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import DiscussionUnit, Message
from app.pipeline.embeddings import Embedder, cosine_similarity, get_embedder


async def assign_message_to_discussion_unit(
    db: AsyncSession,
    message: Message,
    embedder: Embedder | None = None,
) -> DiscussionUnit:
    """Stage 0 (SPEC.md §5): group a message into a discussion unit.

    Order of preference, per spec: reply/thread structure first, then
    temporal proximity + participant overlap + embedding similarity, else
    open a new unit. `project_id` is a hard boundary (ADR-0003/0005) — this
    only ever looks at units within the same project and channel.
    """
    embedder = embedder or get_embedder()
    if message.embedding is None:
        message.embedding = embedder.embed(message.content)

    if message.reply_to_message_id:
        parent = await db.scalar(
            select(Message).where(Message.discord_message_id == message.reply_to_message_id)
        )
        if parent is not None and parent.discussion_unit_id is not None:
            unit = await db.get(DiscussionUnit, parent.discussion_unit_id)
            if unit is not None and unit.status == "open":
                return _join_unit(unit, message)

    cutoff = message.created_at - timedelta(minutes=settings.reconstruction_inactivity_minutes)
    open_units = await db.scalars(
        select(DiscussionUnit)
        .where(
            DiscussionUnit.project_id == message.project_id,
            DiscussionUnit.channel_id == message.channel_id,
            DiscussionUnit.status == "open",
            DiscussionUnit.last_message_at >= cutoff,
        )
        .order_by(DiscussionUnit.last_message_at.desc())
    )

    # Score every open unit by embedding similarity, comparing against every
    # message already in the unit (not just the most recent one) — a
    # low-content reply ("hi", "ok") can otherwise become the sole comparison
    # point and mask an on-topic match.
    scored_units = []
    for unit in open_units:
        unit_embeddings = (
            await db.scalars(
                select(Message.embedding).where(
                    Message.discussion_unit_id == unit.id,
                    Message.embedding.is_not(None),
                )
            )
        ).all()
        similarity = max(
            (cosine_similarity(emb, message.embedding) for emb in unit_embeddings),
            default=0.0,
        )
        scored_units.append((unit, similarity))

    # A genuinely strong topical match always wins, regardless of who's
    # spoken in the unit before — this is what keeps two people's
    # simultaneous, interleaved-but-unrelated conversations apart even
    # though both are "participants" of both units.
    strong_matches = [
        (unit, sim)
        for unit, sim in scored_units
        if sim >= settings.reconstruction_similarity_threshold
    ]
    if strong_matches:
        best_unit, _ = max(strong_matches, key=lambda pair: pair[1])
        return _join_unit(best_unit, message)

    # Nothing scored well on content alone (common for short, low-content
    # messages like "hi" or "ok"). Fall back to conversational continuity:
    # rejoin a unit this author was already part of, picking the
    # highest-similarity one if more than one qualifies.
    participant_matches = [
        (unit, sim) for unit, sim in scored_units if message.author_id in unit.participant_ids
    ]
    if participant_matches:
        best_unit, _ = max(participant_matches, key=lambda pair: pair[1])
        return _join_unit(best_unit, message)

    unit = DiscussionUnit(
        project_id=message.project_id,
        channel_id=message.channel_id,
        status="open",
        opened_at=message.created_at,
        last_message_at=message.created_at,
        participant_ids=[message.author_id],
        last_embedding=message.embedding,
    )
    db.add(unit)
    await db.flush()
    message.discussion_unit_id = unit.id
    return unit


def _join_unit(unit: DiscussionUnit, message: Message) -> DiscussionUnit:
    message.discussion_unit_id = unit.id
    unit.last_message_at = message.created_at
    unit.last_embedding = message.embedding
    if message.author_id not in unit.participant_ids:
        unit.participant_ids = [*unit.participant_ids, message.author_id]
    return unit
