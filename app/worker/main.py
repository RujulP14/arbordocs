import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select

from app.config import settings
from app.db.models import (
    Candidate,
    Decision,
    DiscussionUnit,
    GitHubInstallation,
    GoogleDriveInstallation,
    utcnow,
)
from app.db.session import async_session
from app.ingestion.discord.client import discord_bot_client
from app.pipeline.audit import log_event
from app.pipeline.candidate_filter import score_unit
from app.pipeline.drive_index import sync_drive_index
from app.pipeline.extraction import extract_decision
from app.pipeline.github_index import sync_repo_index
from app.pipeline.reconciliation import reconcile_decision
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
            await log_event(
                db,
                unit.project_id,
                "unit_closed",
                "discussion_unit",
                unit.id,
                payload={"close_reason": unit.close_reason},
            )

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
            if candidate is not None:
                await db.flush()
                await log_event(
                    db,
                    candidate.project_id,
                    "candidate_flagged",
                    "candidate",
                    candidate.id,
                    payload={
                        "score": candidate.score,
                        "matched_keywords": candidate.matched_keywords,
                        "embedding_score": candidate.embedding_score,
                        "reaction_signal": candidate.reaction_signal,
                    },
                )
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
            if decision is not None:
                await db.flush()
                await log_event(
                    db,
                    decision.project_id,
                    "decision_extracted",
                    "decision",
                    decision.id,
                    payload={
                        "statement": decision.statement,
                        "type": decision.type,
                        "confidence": decision.confidence,
                    },
                )
                if decision.decider:
                    portal_url = f"{settings.base_url}/projects/{decision.project_id}/portal/{decision.id}"
                    message = f'ArborDocs noted this decision: "{decision.statement}"\n{portal_url}'
                    try:
                        await discord_bot_client.send_dm(decision.decider, message)
                    except Exception:
                        logger.exception(
                            "failed to DM decider: decision=%s decider=%s", decision.id, decision.decider
                        )
                        await log_event(
                            db,
                            decision.project_id,
                            "decider_notification_failed",
                            "decision",
                            decision.id,
                            payload={"decider": decision.decider},
                        )
                    else:
                        await log_event(
                            db,
                            decision.project_id,
                            "decider_notified",
                            "decision",
                            decision.id,
                            payload={"decider": decision.decider},
                        )
            else:
                await log_event(
                    db,
                    fresh_candidate.project_id,
                    "decision_gated_out",
                    "candidate",
                    fresh_candidate.id,
                )
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
            for c in classifications:
                await log_event(
                    db,
                    fresh_decision.project_id,
                    "supersession_classified",
                    "decision",
                    fresh_decision.id,
                    payload={
                        "existing_decision_id": str(c["existing_decision_id"]),
                        "relationship": c["relationship"],
                        "confidence": c["confidence"],
                        "similarity": c["similarity"],
                    },
                )
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


async def run_reconciliation(decisions: list[Decision]) -> None:
    """Phase 5 tier-b reconciliation (SPEC.md §4) over each newly-extracted
    decision — surfaces related repo code/docs by embedding similarity for a
    human to confirm. No-op per decision if it has no scope, no statement
    embedding, or the project has no synced RepoDocument rows yet.
    """
    async with async_session() as db:
        for decision in decisions:
            fresh_decision = await db.get(Decision, decision.id)
            reconciliation = await reconcile_decision(db, fresh_decision)
            if reconciliation is not None:
                await log_event(
                    db,
                    fresh_decision.project_id,
                    "reconciliation_computed",
                    "decision",
                    fresh_decision.id,
                    payload=reconciliation,
                )
            await db.commit()
            if reconciliation is not None:
                logger.info(
                    "decision reconciled: decision=%s related_code=%d related_docs=%d",
                    fresh_decision.id,
                    len(reconciliation["related_code"]),
                    len(reconciliation["related_docs"]),
                )
            else:
                logger.debug("no reconciliation performed: decision=%s", fresh_decision.id)


async def run_github_sync() -> None:
    """Phase 5 GitHub content index (SPEC.md §4). Runs at its own, much
    slower interval than the rest of the poll loop (repo content changes far
    less often than Discord chat) — gated by each installation's
    `last_synced_at` rather than a separate process/schedule, to fit the
    existing single-worker-process deploy model.
    """
    cutoff = utcnow() - timedelta(seconds=settings.github_sync_interval_seconds)
    async with async_session() as db:
        installations = (
            await db.scalars(
                select(GitHubInstallation).where(
                    (GitHubInstallation.last_synced_at.is_(None))
                    | (GitHubInstallation.last_synced_at < cutoff)
                )
            )
        ).all()

        for installation in installations:
            documents = await sync_repo_index(db, installation.project_id)
            installation.last_synced_at = utcnow()
            await db.commit()
            logger.info(
                "github repo synced: project=%s repo=%s documents=%d",
                installation.project_id,
                installation.repo_full_name,
                len(documents),
            )


async def run_google_sync() -> None:
    """Google Drive content index (issue #14, piece 1). Same
    last_synced_at/interval gating as run_github_sync, its own config
    setting since Drive content likely changes on a different cadence.
    """
    cutoff = utcnow() - timedelta(seconds=settings.google_sync_interval_seconds)
    async with async_session() as db:
        installations = (
            await db.scalars(
                select(GoogleDriveInstallation).where(
                    (GoogleDriveInstallation.last_synced_at.is_(None))
                    | (GoogleDriveInstallation.last_synced_at < cutoff)
                )
            )
        ).all()

        for installation in installations:
            documents = await sync_drive_index(db, installation.project_id)
            installation.last_synced_at = utcnow()
            await db.commit()
            logger.info(
                "google drive folder synced: project=%s folder=%s documents=%d",
                installation.project_id,
                installation.folder_id,
                len(documents),
            )


async def poll_once() -> None:
    closed = await close_due_units()
    if closed:
        logger.info("closed %d discussion unit(s)", len(closed))
        candidates = await run_candidate_filter(closed)
        if candidates:
            decisions = await run_extraction(candidates)
            if decisions:
                await run_supersession(decisions)
                await run_reconciliation(decisions)
    await run_github_sync()
    await run_google_sync()


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
