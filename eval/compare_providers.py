"""Phase 4, Stage 2: side-by-side comparison of LLM providers for gate + extraction.

By default runs 5 representative threads (2 true decisions, 1 joke/casual
false-positive from the Phase 3 eval, 1 unresolved proposal, 1 real Discord
thread) through app/pipeline/extraction.py's extract_decision() for each
configured provider (Groq / Ollama), and prints a side-by-side report so a
human can compare gate accuracy and extraction quality before picking a
default provider. Pass --full to run the entire 24-thread labeled dataset
(eval/dataset.py) instead, plus a summary gate-accuracy tally per provider.

Setup per provider:
  - groq:   set GROQ_API_KEY in .env (free, no credit card — console.groq.com)
  - ollama: run `ollama serve` locally + `ollama pull qwen2.5:7b` (no key)

Usage:
    uv run python -m eval.compare_providers [--providers groq,ollama] [--full] [--verbose]
"""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import (
    Base,
    Candidate,
    DiscordGuild,
    DiscussionUnit,
    Message,
    Project,
    ProjectChannel,
    User,
)
from app.pipeline.extraction import extract_decision
from eval.dataset import DATASET

BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)

# Representative threads: 2 true decisions, 1 joke (the eval harness's actual
# false-positive case), 1 unresolved proposal — plus one real Discord thread
# appended separately below (not from the synthetic dataset).
COMPARISON_THREAD_IDS = [
    "tech-pagination",
    "policy-oncall-rotation",
    "joke-standup-banter",
    "proposal-unresolved-cache",
]

REAL_DISCORD_THREAD = [
    ("rujul14", "hi"),
    ("rujul14", "should we paginate the /users endpoint by offset or cursor?"),
    ("rujul0089", "Cursor is better for large scale tables, offset breaks on inserts"),
    ("rujul14", "ok, let's go with cursor-based pagination then"),
]

ALL_PROVIDERS = ["groq", "ollama"]


async def _make_project(db) -> Project:
    admin = User(github_login="compare-bot", is_admin=True)
    db.add(admin)
    await db.flush()
    project = Project(name="Compare Project", created_by=admin.id)
    db.add(project)
    await db.flush()
    guild = DiscordGuild(guild_id="guild-1")
    db.add(guild)
    await db.flush()
    db.add(
        ProjectChannel(
            project_id=project.id,
            discord_guild_id=guild.id,
            channel_id="chan-1",
            authority_tier="medium",
        )
    )
    await db.commit()
    return project


async def _make_candidate(db, project: Project, label: str, messages: list[tuple[str, str]]) -> Candidate:
    unit = DiscussionUnit(project_id=project.id, channel_id="chan-1", status="closed")
    db.add(unit)
    await db.flush()

    participant_ids = []
    for i, (author, content) in enumerate(messages):
        db.add(
            Message(
                project_id=project.id,
                channel_id="chan-1",
                discussion_unit_id=unit.id,
                discord_message_id=f"{label}-{i}",
                author_id=author,
                author_name=author,
                content=content,
                reactions=[],
                created_at=BASE_TIME + timedelta(seconds=30 * i),
            )
        )
        if author not in participant_ids:
            participant_ids.append(author)
    unit.participant_ids = participant_ids
    await db.flush()

    candidate = Candidate(project_id=project.id, discussion_unit_id=unit.id, score=1.0)
    db.add(candidate)
    await db.commit()
    return candidate


def _print_result(provider: str, label: str, expected_decision: bool, decision, error: str | None) -> None:
    if error is not None:
        print(f"  [{provider:6s}] ERROR: {error}")
        return
    if decision is None:
        verdict = "correctly gated out" if not expected_decision else "INCORRECTLY gated out (missed)"
        print(f"  [{provider:6s}] resolved=False — {verdict}")
        return
    verdict = "" if expected_decision else " — INCORRECTLY flagged as a decision"
    print(f"  [{provider:6s}] resolved=True{verdict}")
    print(f"           statement:  {decision.statement!r}")
    print(f"           type:       {decision.type}")
    print(f"           rationale:  {decision.rationale!r}")
    print(f"           message_ids:{decision.message_ids}")
    print(f"           confidence: {decision.confidence}")


async def run_comparison(providers: list[str], verbose: bool, full: bool) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    if full:
        cases: list[tuple[str, bool, list[tuple[str, str]]]] = [
            (thread.id, thread.is_decision, [(lm.author_id, lm.content) for lm in thread.messages])
            for thread in DATASET
        ]
    else:
        thread_by_id = {t.id: t for t in DATASET}
        cases = []
        for thread_id in COMPARISON_THREAD_IDS:
            thread = thread_by_id[thread_id]
            messages = [(lm.author_id, lm.content) for lm in thread.messages]
            cases.append((thread_id, thread.is_decision, messages))
        cases.append(("real-discord-pagination", True, REAL_DISCORD_THREAD))

    # correct[provider] / total[provider] — gate accuracy tally, most useful
    # with --full where scrolling through 24 per-thread blocks isn't practical.
    correct = dict.fromkeys(providers, 0)
    errors = dict.fromkeys(providers, 0)
    total = len(cases)

    async with session_maker() as db:
        project = await _make_project(db)
        project_id = project.id  # capture now — a rollback below expires the ORM object

        for label, expected_decision, messages in cases:
            print(f"=== {label} (expected decision={expected_decision}) ===")
            for provider in providers:
                project = await db.get(Project, project_id)
                candidate = await _make_candidate(db, project, f"{label}-{provider}", messages)
                try:
                    decision = await extract_decision(db, candidate, provider=provider)
                    await db.commit()
                    _print_result(provider, label, expected_decision, decision, error=None)
                    got_decision = decision is not None
                    if got_decision == expected_decision:
                        correct[provider] += 1
                except Exception as exc:  # noqa: BLE001 — surfacing provider errors is the point
                    await db.rollback()
                    _print_result(provider, label, expected_decision, None, error=str(exc)[:200])
                    errors[provider] += 1
            print()

    await engine.dispose()

    if full:
        print("=== Gate accuracy summary ===")
        for provider in providers:
            n_errors = errors[provider]
            print(
                f"  [{provider:6s}] {correct[provider]}/{total} correct"
                + (f"  ({n_errors} errored)" if n_errors else "")
            )


def cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--providers",
        default=",".join(ALL_PROVIDERS),
        help=f"comma-separated list of providers to compare (default: all — {ALL_PROVIDERS})",
    )
    parser.add_argument(
        "--full", action="store_true", help="run the entire 24-thread labeled dataset, not just 5"
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    for p in providers:
        if p not in ALL_PROVIDERS:
            parser.error(f"unknown provider {p!r} — choose from {ALL_PROVIDERS}")
    asyncio.run(run_comparison(providers, args.verbose, args.full))


if __name__ == "__main__":
    cli()
