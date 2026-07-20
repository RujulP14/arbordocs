import logging

import discord
from sqlalchemy import select

from app.config import settings
from app.db.models import Message, ProjectChannel
from app.db.session import async_session

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
        project_channel = tracked.get(str(message.channel.id))
        if project_channel is None:
            return  # untracked channel — never ingested, per ADR-0003/0005
        await self._store_message(message, project_channel.project_id)

    async def _store_message(self, message: discord.Message, project_id) -> None:
        async with async_session() as db:
            existing = await db.scalar(select(Message).where(Message.discord_message_id == str(message.id)))
            if existing:
                return

            db.add(
                Message(
                    project_id=project_id,
                    channel_id=str(message.channel.id),
                    discord_message_id=str(message.id),
                    author_id=str(message.author.id),
                    author_name=str(message.author),
                    author_roles=[r.name for r in getattr(message.author, "roles", [])],
                    content=message.content,
                    reply_to_message_id=(str(message.reference.message_id) if message.reference else None),
                    reactions=[{"emoji": str(r.emoji), "count": r.count} for r in message.reactions],
                    created_at=message.created_at,
                )
            )
            await db.commit()


def run() -> None:
    logging.basicConfig(level=settings.log_level.upper())
    bot = ArborDocsBot()
    bot.run(settings.discord_bot_token)


if __name__ == "__main__":
    run()
