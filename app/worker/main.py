import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select

from app.config import settings
from app.db.models import Candidate, Decision, DiscussionUnit, utcnow
from app.db.session import async_session
from app.pipeline.candidate_filter import score_unit
from app.pipeline.extraction import extract_decision
from app.pipeline.supersession import classify_relationship

logger = logging.getLogger("arbordocs.worker")


async def close_due_units() -> list[DiscussionUnit]:
    """Closes units that requested a signal-close, or have gone quiet past
    the inactivity window (ARCHITECTURE.md step 3). Returns the closed units.
    """
    cutoff = utcnow() - timedelta(minutes=settings.reconstruction_inactivity_minutes)
    async with async_session() as db:
        units = (
            await db.scalars(
                select(DiscussionUnit).where(
                    DiscussionUnit.status == "open",
                    (DiscussionUnit.signal_close_requested.is_(True))
                    | (DiscussionUnit.last_message_at < cutoff),
                )
            )
        ).all()

        closed = []
        for unit in units:
            unit.status = "closed"
            unit.closed_at = utcnow()
            unit.close_reason = "signal" if unit.signal_close_requested else "inactivity"
            closed.append(unit)

        await db.commit()
        for unit in closed:
            await db.refresh(unit)
        return closed


async def run_candidate_filter(units: list[DiscussionUnit]) -> list[Candidate]:
    """Stage 1 over each newly-closed unit (ARCHITECTURE.md step 4)."""
    candidates = []
    async with async_session() as db:
        for unit in units:
            fresh_unit = await db.get(DiscussionUnit, unit.id)
            candidate = await score_unit(db, fresh_unit)
            await db.commit()
            if candidate is not None:
                logger.info(
                    "candidate flagged: discussion_unit=%s score=%.2f keywords=%s embedding_score=%.2f reaction=%s",
                    fresh_unit.id,
                    candidate.score,
                    candidate.matched_keywords,
                    candidate.embedding_score,
                    candidate.reaction_signal,
                )
                await db.refresh(candidate)
                candidates.append(candidate)
            else:
                logger.debug("no candidate signal: discussion_unit=%s", fresh_unit.id)
    return candidates


async def run_extraction(candidates: list[Candidate]) -> list[Decision]:
    """Stage 2 (SPEC.md §5) over each newly-flagged candidate."""
    decisions = []
    async with async_session() as db:
        for candidate in candidates:
            fresh_candidate = await db.get(Candidate, candidate.id)
            decision = await extract_decision(db, fresh_candidate)
            await db.commit()
            if decision is not None:
                logger.info(
                    "decision extracted: candidate=%s statement=%r type=%s confidence=%.2f",
                    fresh_candidate.id,
                    decision.statement,
                    decision.type,
                    decision.confidence,
                )
                await db.refresh(decision)
                decisions.append(decision)
            else:
                logger.debug(
                    "candidate gated out (not a resolved decision): candidate=%s", fresh_candidate.id
                )
    return decisions


async def run_supersession(decisions: list[Decision]) -> None:
    """Stage 3 (SPEC.md §5) over each newly-extracted decision."""
    async with async_session() as db:
        for decision in decisions:
            fresh_decision = await db.get(Decision, decision.id)
            classifications = await classify_relationship(db, fresh_decision)
            await db.commit()
            for c in classifications:
                logger.info(
                    "decision %s vs %s: relationship=%s similarity=%.2f confidence=%.2f",
                    fresh_decision.id,
                    c["existing_decision_id"],
                    c["relationship"],
                    c["similarity"],
                    c["confidence"],
                )
            if not classifications:
                logger.debug("no similar active decisions found: decision=%s", fresh_decision.id)


async def poll_once() -> None:
    closed = await close_due_units()
    if closed:
        logger.info("closed %d discussion unit(s)", len(closed))
        candidates = await run_candidate_filter(closed)
        if candidates:
            decisions = await run_extraction(candidates)
            if decisions:
                await run_supersession(decisions)


async def run_forever() -> None:
    logger.info(
        "worker started: poll_interval=%ss inactivity_minutes=%s",
        settings.worker_poll_interval_seconds,
        settings.reconstruction_inactivity_minutes,
    )
    while True:
        try:
            await poll_once()
        except Exception:
            logger.exception("poll_once failed")
        await asyncio.sleep(settings.worker_poll_interval_seconds)


def run() -> None:
    logging.basicConfig(level=settings.log_level.upper())
    asyncio.run(run_forever())


if __name__ == "__main__":
    run()
