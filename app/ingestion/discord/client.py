import httpx

from app.config import settings

DISCORD_API = "https://discord.com/api/v10"

# Permissions integer for: View Channels, Read Message History, Add Reactions.
# Enough for the bot to read chat and reactions without moderation/admin scope.
BOT_PERMISSIONS = 66560

# Discord channel type 0 = GUILD_TEXT.
GUILD_TEXT_CHANNEL_TYPE = 0


class DiscordBotClient:
    """Talks to Discord's REST API as the ArborDocs bot application.

    One shared bot invited into many guilds (ADR-0005) — every call here is
    scoped by a `guild_id` the caller supplies.
    """

    def invite_url(self, redirect_uri: str, state: str) -> str:
        return (
            "https://discord.com/api/oauth2/authorize"
            f"?client_id={settings.discord_oauth_client_id}"
            "&scope=bot"
            f"&permissions={BOT_PERMISSIONS}"
            f"&redirect_uri={redirect_uri}"
            "&response_type=code"
            f"&state={state}"
        )

    async def list_guild_text_channels(self, guild_id: str) -> list[dict]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{DISCORD_API}/guilds/{guild_id}/channels",
                headers={"Authorization": f"Bot {settings.discord_bot_token}"},
            )
            resp.raise_for_status()
            channels = resp.json()
            return [c for c in channels if c.get("type") == GUILD_TEXT_CHANNEL_TYPE]

    async def fetch_guild(self, guild_id: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{DISCORD_API}/guilds/{guild_id}",
                headers={"Authorization": f"Bot {settings.discord_bot_token}"},
            )
            resp.raise_for_status()
            return resp.json()


discord_bot_client = DiscordBotClient()
