"""Phase 3 eval harness (SPEC.md §7): decision-detection F1 + Stage 0 grouping purity.

Runs the labeled synthetic dataset (eval/dataset.py) through the REAL Stage 0
(app/pipeline/reconstruction.py) + Stage 1 (app/pipeline/candidate_filter.py)
pipeline — real embedding model, not the test suite's FakeEmbedder — and
reports:

1. Decision-detection precision/recall/F1 (the SPEC.md §7 headline metric):
   each labeled thread runs on its own isolated channel, so Stage 0 grouping
   noise can't contaminate the Stage 1 classification signal being measured.
2. Stage 0 grouping purity: a deliberately interleaved multi-topic scenario
   (SPEC.md §7's "with/without Stage 0" ablation guidance), reported
   separately, since embedding-similarity-only grouping is known to be
   imperfect on short, low-content, no-reply cross-topic chat (see
   docs/changes/CHANGELOG.md).

Usage:
    uv run python -m eval.harness [--verbose]
"""

import argparse
import asyncio
from collections import Counter
from datetime import UTC, datetime, timedelta

from sklearn.metrics import precision_recall_fscore_support
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, DiscussionUnit, Message, Project, User
from app.pipeline.candidate_filter import score_unit
from app.pipeline.embeddings import get_embedder
from eval.dataset import DATASET, INTERLEAVED_GROUPS, LabeledThread

BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def compute_detection_metrics(y_true: list[bool], y_pred: list[bool]) -> tuple[float, float, float]:
    """Precision/recall/F1 for the decision-detection headline metric (SPEC.md §7)."""
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average="binary", pos_label=True, zero_division=0
    )
    return float(precision), float(recall), float(f1)


async def _make_project(db) -> Project:
    admin = User(github_login="eval-bot", is_admin=True)
    db.add(admin)
    await db.flush()
    project = Project(name="Eval Project", created_by=admin.id)
    db.add(project)
    await db.flush()
    return project


async def _ingest_thread(db, project: Project, thread: LabeledThread, channel_id: str, embedder) -> None:
    """Insert a thread's messages in order, running them through Stage 0."""
    from app.pipeline.reconstruction import assign_message_to_discussion_unit

    prev_discord_id: str | None = None
    for i, lm in enumerate(thread.messages):
        discord_id = f"{thread.id}-{i}"
        reactions = [{"emoji": "✅", "count": 1}] if lm.checkmark_reaction else []
        msg = Message(
            project_id=project.id,
            channel_id=channel_id,
            discord_message_id=discord_id,
            author_id=lm.author_id,
            content=lm.content,
            reply_to_message_id=(prev_discord_id if lm.is_reply else None),
            reactions=reactions,
            created_at=BASE_TIME + timedelta(seconds=lm.offset_seconds),
        )
        db.add(msg)
        await db.flush()
        await assign_message_to_discussion_unit(db, msg, embedder=embedder)
        await db.commit()
        prev_discord_id = discord_id


async def run_decision_detection_eval(db, project: Project, embedder, verbose: bool) -> None:
    y_true: list[bool] = []
    y_pred: list[bool] = []
    mismatches: list[tuple[str, bool, bool]] = []

    for thread in DATASET:
        channel_id = f"eval-{thread.id}"
        await _ingest_thread(db, project, thread, channel_id, embedder)

        units = (
            await db.scalars(
                select(DiscussionUnit).where(
                    DiscussionUnit.project_id == project.id,
                    DiscussionUnit.channel_id == channel_id,
                )
            )
        ).all()

        predicted = False
        for unit in units:
            unit.status = "closed"
            await db.commit()
            candidate = await score_unit(db, unit, embedder=embedder)
            await db.commit()
            if candidate is not None:
                predicted = True

        y_true.append(thread.is_decision)
        y_pred.append(predicted)
        if predicted != thread.is_decision:
            mismatches.append((thread.id, thread.is_decision, predicted))

    precision, recall, f1 = compute_detection_metrics(y_true, y_pred)

    print("=== Decision detection (Stage 0 + Stage 1) ===")
    print(f"threads: {len(DATASET)}  precision={precision:.2f}  recall={recall:.2f}  f1={f1:.2f}")
    if verbose and mismatches:
        print("mismatches (thread_id, expected, predicted):")
        for thread_id, expected, predicted in mismatches:
            print(f"  {thread_id:30s} expected={expected!s:5s} predicted={predicted!s:5s}")
    print()


async def run_stage0_grouping_eval(db, project: Project, embedder, verbose: bool) -> None:
    thread_by_id = {t.id: t for t in DATASET}
    total_correct = 0
    total_messages = 0

    for group_idx, group in enumerate(INTERLEAVED_GROUPS):
        from app.pipeline.reconstruction import assign_message_to_discussion_unit

        channel_id = f"eval-interleave-{group_idx}"
        threads = [thread_by_id[tid] for tid in group]

        # Round-robin interleave messages across the group's threads, each
        # message 30s apart, so they land in one shared channel — the
        # deliberately hard case (SPEC.md §7 ablation guidance).
        interleaved: list[tuple[str, object]] = []
        for msgs in zip(*[t.messages for t in threads], strict=False):
            for thread, lm in zip(threads, msgs, strict=True):
                interleaved.append((thread.id, lm))

        message_to_unit: dict[str, str] = {}
        prev_discord_id_by_thread: dict[str, str | None] = dict.fromkeys(group)
        for i, (thread_id, lm) in enumerate(interleaved):
            discord_id = f"{thread_id}-il-{i}"
            msg = Message(
                project_id=project.id,
                channel_id=channel_id,
                discord_message_id=discord_id,
                author_id=lm.author_id,
                content=lm.content,
                reply_to_message_id=(prev_discord_id_by_thread[thread_id] if lm.is_reply else None),
                reactions=[],
                created_at=BASE_TIME + timedelta(seconds=30 * i),
            )
            db.add(msg)
            await db.flush()
            unit = await assign_message_to_discussion_unit(db, msg, embedder=embedder)
            await db.commit()
            message_to_unit[discord_id] = str(unit.id)
            prev_discord_id_by_thread[thread_id] = discord_id

        # Purity: for each unit, the majority source-thread is "correct" for
        # that unit; every message from a different thread landing in it is
        # a grouping error.
        unit_thread_counts: dict[str, Counter] = {}
        for i, (thread_id, _lm) in enumerate(interleaved):
            discord_id = f"{thread_id}-il-{i}"
            unit_id = message_to_unit[discord_id]
            unit_thread_counts.setdefault(unit_id, Counter())[thread_id] += 1

        majority_thread_by_unit = {
            unit_id: counts.most_common(1)[0][0] for unit_id, counts in unit_thread_counts.items()
        }

        group_correct = 0
        for i, (thread_id, _lm) in enumerate(interleaved):
            discord_id = f"{thread_id}-il-{i}"
            unit_id = message_to_unit[discord_id]
            if majority_thread_by_unit[unit_id] == thread_id:
                group_correct += 1
        total_correct += group_correct
        total_messages += len(interleaved)

        if verbose:
            print(f"  group {group}: {group_correct}/{len(interleaved)} correctly grouped")

    purity = total_correct / total_messages if total_messages else 0.0
    print("=== Stage 0 grouping purity (interleaved multi-topic stress case) ===")
    print(f"messages: {total_messages}  purity={purity:.2f}")
    print()


async def main(verbose: bool) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    embedder = get_embedder()

    async with session_maker() as db:
        project = await _make_project(db)
        await run_decision_detection_eval(db, project, embedder, verbose)
        await run_stage0_grouping_eval(db, project, embedder, verbose)

    await engine.dispose()


def cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="show per-thread mismatches")
    args = parser.parse_args()
    asyncio.run(main(args.verbose))


if __name__ == "__main__":
    cli()
