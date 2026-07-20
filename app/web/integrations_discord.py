import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import DiscordGuild, Project, ProjectChannel, User
from app.db.session import get_db
from app.ingestion.discord.client import discord_bot_client
from app.web.deps import require_admin
from app.web.templating import templates

router = APIRouter(prefix="/integrations/discord", tags=["integrations-discord"])


def _callback_url() -> str:
    return f"{settings.base_url}/integrations/discord/callback"


@router.get("/connect/{project_id}")
async def connect(
    project_id: uuid.UUID, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> RedirectResponse:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404)
    url = discord_bot_client.invite_url(redirect_uri=_callback_url(), state=str(project_id))
    return RedirectResponse(url)


@router.get("/callback")
async def callback(
    request: Request,
    guild_id: str,
    state: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    project_id = uuid.UUID(state)
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404)

    guild_info = await discord_bot_client.fetch_guild(guild_id)
    guild = await db.scalar(select(DiscordGuild).where(DiscordGuild.guild_id == guild_id))
    if guild is None:
        guild = DiscordGuild(guild_id=guild_id, guild_name=guild_info.get("name"))
        db.add(guild)
        await db.commit()
        await db.refresh(guild)

    channels = await discord_bot_client.list_guild_text_channels(guild_id)
    return templates.TemplateResponse(
        request,
        "discord_channel_picker.html",
        {
            "user": user,
            "project": project,
            "guild": guild,
            "channels": channels,
        },
    )


@router.post("/attach/{project_id}")
async def attach(
    project_id: uuid.UUID,
    discord_guild_id: uuid.UUID = Form(...),
    channels: list[str] = Form([]),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    # Each `channels` value is "channel_id|channel_name" — encoded as one
    # checkbox value so id/name can't drift apart across two parallel lists.
    for raw in channels:
        channel_id, _, channel_name = raw.partition("|")
        existing = await db.scalar(select(ProjectChannel).where(ProjectChannel.channel_id == channel_id))
        if existing:
            existing.project_id = project_id
            existing.discord_guild_id = discord_guild_id
            existing.channel_name = channel_name
        else:
            db.add(
                ProjectChannel(
                    project_id=project_id,
                    discord_guild_id=discord_guild_id,
                    channel_id=channel_id,
                    channel_name=channel_name,
                )
            )
    await db.commit()
    return RedirectResponse(f"/projects/{project_id}", status_code=303)
