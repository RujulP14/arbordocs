import logging

import discord
from sqlalchemy import select

from app.config import settings
from app.db.models import DiscussionUnit, Message, ProjectChannel
from app.db.session import async_session
from app.pipeline.candidate_filter import CHECK_MARK_EMOJI
from app.pipeline.reconstruction import assign_message_to_discussion_unit

logger = logging.getLogger("arbordocs.discord_bot")

BACKFILL_LIMIT = 500


class ArborDocsBot(discord.Client):
    """Serves every guild the shared bot has been invited to (ADR-0005).

    Routing a message to a project is a channel_id -> project_id lookup
    against `project_channels`; channels never explicitly attached to a
    project are never written to `messages` at all (ADR-0003).
    """

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.reactions = True
        super().__init__(intents=intents)

    async def on_ready(self) -> None:
        logger.info("Logged in as %s", self.user)
        await self._backfill_tracked_channels()

    async def _tracked_channel_ids(self) -> dict[str, "ProjectChannel"]:
        async with async_session() as db:
            rows = await db.scalars(select(ProjectChannel))
            return {row.channel_id: row for row in rows}

    async def _backfill_tracked_channels(self) -> None:
        tracked = await self._tracked_channel_ids()
        for channel_id, project_channel in tracked.items():
            channel = self.get_channel(int(channel_id))
            if channel is None:
                logger.warning("Tracked channel %s not visible to bot, skipping backfill", channel_id)
                continue

            last_seen = await self._last_ingested_message_id(project_channel.project_id, channel_id)
            after = discord.Object(id=int(last_seen)) if last_seen else None

            async for message in channel.history(limit=BACKFILL_LIMIT, after=after, oldest_first=True):
                await self._store_message(message, project_channel.project_id)

            await self._backfill_channel_threads(channel, project_channel)

    async def _backfill_channel_threads(self, channel, project_channel: "ProjectChannel") -> None:
        """Threads aren't covered by the parent channel's `history()` call —
        each thread needs its own backfill, active and archived alike
        (issue #11: Discord Threads were previously invisible entirely).
        """
        threads = list(getattr(channel, "threads", []))
        archived_iter = getattr(channel, "archived_threads", None)
        if archived_iter is not None:
            async for thread in archived_iter():
                threads.append(thread)

        for thread in threads:
            last_seen = await self._last_ingested_message_id(project_channel.project_id, str(thread.id))
            after = discord.Object(id=int(last_seen)) if last_seen else None
            async for message in thread.history(limit=BACKFILL_LIMIT, after=after, oldest_first=True):
                await self._store_message(message, project_channel.project_id)

    async def _last_ingested_message_id(self, project_id, channel_id: str) -> str | None:
        async with async_session() as db:
            row = await db.scalar(
                select(Message)
                .where(Message.project_id == project_id, Message.channel_id == channel_id)
                .order_by(Message.created_at.desc())
                .limit(1)
            )
            return row.discord_message_id if row else None

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        tracked = await self._tracked_channel_ids()
        # A Thread's own id is distinct from the channel it was created in
        # (issue #11) — track by the parent channel's id so messages inside
        # a Thread of a tracked channel are ingested, not silently dropped.
        if isinstance(message.channel, discord.Thread):
            lookup_id = str(message.channel.parent_id)
        else:
            lookup_id = str(message.channel.id)
        project_channel = tracked.get(lookup_id)
        if project_channel is None:
            return  # untracked channel — never ingested, per ADR-0003/0005
        await self._store_message(message, project_channel.project_id)

    async def _store_message(self, message: discord.Message, project_id) -> None:
        async with async_session() as db:
            existing = await db.scalar(select(Message).where(Message.discord_message_id == str(message.id)))
            if existing:
                return

            row = Message(
                project_id=project_id,
                channel_id=str(message.channel.id),
                discord_message_id=str(message.id),
                author_id=str(message.author.id),
                author_name=str(message.author),
                author_roles=[r.name for r in getattr(message.author, "roles", [])],
                content=message.content,
                reply_to_message_id=(str(message.reference.message_id) if message.reference else None),
                thread_starter_message_id=self._thread_starter_message_id(message),
                reactions=[{"emoji": str(r.emoji), "count": r.count} for r in message.reactions],
                created_at=message.created_at,
            )
            db.add(row)
            await db.flush()
            # Stage 0 (SPEC.md §5) — group into a discussion unit right after
            # insert, so both live on_message and backfill go through the
            # same reconstruction path.
            await assign_message_to_discussion_unit(db, row)
            await db.commit()

    @staticmethod
    def _thread_starter_message_id(message: discord.Message) -> str | None:
        """A Thread's own id equals its starter message's id (issue #11) —
        the starter message itself is posted in the parent channel, never
        inside the thread, so this never self-references. `None` for
        threads with no starter message (e.g. forum/private threads) or
        plain channel messages.
        """
        if isinstance(message.channel, discord.Thread):
            return str(message.channel.id)
        return None

    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User) -> None:
        if str(reaction.emoji) != CHECK_MARK_EMOJI:
            return
        tracked = await self._tracked_channel_ids()
        # Same thread-vs-parent-channel distinction as on_message (issue #11).
        if isinstance(reaction.message.channel, discord.Thread):
            lookup_id = str(reaction.message.channel.parent_id)
        else:
            lookup_id = str(reaction.message.channel.id)
        if lookup_id not in tracked:
            return

        async with async_session() as db:
            message_row = await db.scalar(
                select(Message).where(Message.discord_message_id == str(reaction.message.id))
            )
            if message_row is None or message_row.discussion_unit_id is None:
                return
            existing_reactions = list(message_row.reactions or [])
            if not any(r.get("emoji") == CHECK_MARK_EMOJI for r in existing_reactions):
                existing_reactions.append({"emoji": CHECK_MARK_EMOJI, "count": 1})
                message_row.reactions = existing_reactions

            unit = await db.get(DiscussionUnit, message_row.discussion_unit_id)
            if unit is not None and unit.status == "open":
                unit.signal_close_requested = True
            await db.commit()


def run() -> None:
    logging.basicConfig(level=settings.log_level.upper())
    bot = ArborDocsBot()
    bot.run(settings.discord_bot_token)


if __name__ == "__main__":
    run()
