import base64
import time

import httpx
import jwt

from app.config import settings

GITHUB_API = "https://api.github.com"


def _load_private_key() -> str:
    return base64.b64decode(settings.github_app_private_key_b64).decode("utf-8")


def sign_app_jwt() -> str:
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + 9 * 60,
        "iss": settings.github_app_id,
    }
    return jwt.encode(payload, _load_private_key(), algorithm="RS256")


class GitHubAppClient:
    """Talks to GitHub as the ArborDocs GitHub App (ADR-0007).

    One App, potentially many installations (one per admin/org) — every call
    here is scoped by an `installation_id` the caller supplies, never by a
    single hardcoded repo.
    """

    def __init__(self) -> None:
        self._app_jwt: str | None = None

    def install_url(self, state: str) -> str:
        return f"https://github.com/apps/{settings.github_app_slug}/installations/new?state={state}"

    def oauth_authorize_url(self, redirect_uri: str, state: str) -> str:
        return (
            "https://github.com/login/oauth/authorize"
            f"?client_id={settings.github_app_client_id}"
            f"&redirect_uri={redirect_uri}"
            f"&state={state}"
        )

    async def exchange_oauth_code(self, code: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": settings.github_app_client_id,
                    "client_secret": settings.github_app_client_secret,
                    "code": code,
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def fetch_identity(self, oauth_token: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GITHUB_API}/user",
                headers={"Authorization": f"Bearer {oauth_token}", "Accept": "application/vnd.github+json"},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_installation_token(self, installation_id: str) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {sign_app_jwt()}",
                    "Accept": "application/vnd.github+json",
                },
            )
            resp.raise_for_status()
            return resp.json()["token"]

    async def list_installation_repos(self, installation_id: str) -> list[dict]:
        token = await self.get_installation_token(installation_id)
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GITHUB_API}/installation/repositories",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            )
            resp.raise_for_status()
            return resp.json()["repositories"]

    async def get_repo_tree(self, installation_id: str, repo_full_name: str) -> list[dict]:
        """Recursive git tree for the repo's default branch — one call gets
        every file path in the repo (path, type, sha), no pagination needed
        for repos under GitHub's tree-size cap (SPEC.md §4's "lightweight
        per-project index" scope).
        """
        token = await self.get_installation_token(installation_id)
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        async with httpx.AsyncClient() as client:
            repo_resp = await client.get(f"{GITHUB_API}/repos/{repo_full_name}", headers=headers)
            repo_resp.raise_for_status()
            default_branch = repo_resp.json()["default_branch"]

            tree_resp = await client.get(
                f"{GITHUB_API}/repos/{repo_full_name}/git/trees/{default_branch}",
                headers=headers,
                params={"recursive": "1"},
            )
            tree_resp.raise_for_status()
            return tree_resp.json()["tree"]

    async def get_file_content(self, installation_id: str, repo_full_name: str, path: str) -> str:
        """Fetch one file's content, decoded from the Contents API's base64 encoding."""
        token = await self.get_installation_token(installation_id)
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GITHUB_API}/repos/{repo_full_name}/contents/{path}",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            )
            resp.raise_for_status()
            return base64.b64decode(resp.json()["content"]).decode("utf-8")


github_app_client = GitHubAppClient()
