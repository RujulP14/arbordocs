import httpx

from app.config import settings

GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_DRIVE_API = "https://www.googleapis.com/drive/v3"
GOOGLE_DOCS_API = "https://docs.googleapis.com/v1"

GOOGLE_DOC_MIME_TYPE = "application/vnd.google-apps.document"
GOOGLE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"

# Docs v1 heading paragraph styles -> markdown heading level, so a Drive
# doc's structured body can be flattened into the same "#"/"##" markdown
# shape app/pipeline/github_index.py's parse_doc_sections already expects
# — no separate parser needed for Drive content.
_HEADING_STYLE_TO_MARKDOWN_PREFIX = {
    "HEADING_1": "# ",
    "HEADING_2": "## ",
    "HEADING_3": "### ",
    "HEADING_4": "#### ",
    "HEADING_5": "##### ",
    "HEADING_6": "###### ",
}


def _flatten_docs_body(document: dict) -> str:
    """Render a Docs v1 `documents.get` response's structured body as
    markdown-heading-style plain text — headings get "#"/"##"/etc.
    prefixes, everything else is plain paragraph text.
    """
    lines = []
    for element in document.get("body", {}).get("content", []):
        paragraph = element.get("paragraph")
        if paragraph is None:
            continue
        text = "".join(
            run.get("textRun", {}).get("content", "") for run in paragraph.get("elements", [])
        ).rstrip("\n")
        if not text:
            lines.append("")
            continue
        style = paragraph.get("paragraphStyle", {}).get("namedStyleType", "")
        prefix = _HEADING_STYLE_TO_MARKDOWN_PREFIX.get(style, "")
        lines.append(f"{prefix}{text}")
    return "\n".join(lines)


class GoogleDriveClient:
    """Talks to Google Drive/Docs as the authorizing admin (issue #14).

    OAuth per-admin, not a shared service account — every call here is
    scoped by a caller-supplied access token, minted fresh from a stored
    `refresh_token` each time (Google's OAuth access tokens expire hourly,
    unlike GitHub's longer-lived installation tokens).
    """

    def oauth_authorize_url(self, redirect_uri: str, state: str) -> str:
        return (
            "https://accounts.google.com/o/oauth2/v2/auth"
            f"?client_id={settings.google_client_id}"
            f"&redirect_uri={redirect_uri}"
            "&response_type=code"
            "&access_type=offline"
            "&prompt=consent"
            "&scope=https://www.googleapis.com/auth/drive.readonly"
            f"&state={state}"
        )

    async def exchange_oauth_code(self, code: str, redirect_uri: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                GOOGLE_OAUTH_TOKEN_URL,
                data={
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def refresh_access_token(self, refresh_token: str) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                GOOGLE_OAUTH_TOKEN_URL,
                data={
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            resp.raise_for_status()
            return resp.json()["access_token"]

    async def list_folders(self, access_token: str) -> list[dict]:
        """Lists folders the connecting admin owns AND folders shared with
        them by someone else — Drive treats these as separate query
        surfaces (a real onboarding/team folder is commonly shared-with,
        not owned, per issue #14 follow-up testing), so both queries run
        and results are merged, de-duplicated by id.
        """
        async with httpx.AsyncClient() as client:
            owned_resp = await client.get(
                f"{GOOGLE_DRIVE_API}/files",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "q": f"mimeType='{GOOGLE_FOLDER_MIME_TYPE}' and trashed=false and 'me' in owners",
                    "fields": "files(id,name)",
                },
            )
            owned_resp.raise_for_status()

            shared_resp = await client.get(
                f"{GOOGLE_DRIVE_API}/files",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "q": f"mimeType='{GOOGLE_FOLDER_MIME_TYPE}' and trashed=false and sharedWithMe",
                    "fields": "files(id,name)",
                },
            )
            shared_resp.raise_for_status()

        seen_ids = set()
        folders = []
        for folder in [*owned_resp.json()["files"], *shared_resp.json()["files"]]:
            if folder["id"] not in seen_ids:
                seen_ids.add(folder["id"])
                folders.append(folder)
        return folders

    async def _list_folder_children(self, access_token: str, folder_id: str) -> list[dict]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GOOGLE_DRIVE_API}/files",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "q": f"'{folder_id}' in parents and trashed=false",
                    "fields": "files(id,name,mimeType)",
                },
            )
            resp.raise_for_status()
            return resp.json()["files"]

    async def list_folder_docs(self, access_token: str, folder_id: str, max_depth: int = 5) -> list[dict]:
        """Lists every Google Doc under `folder_id`, recursing into
        subfolders — Drive v3's `files.list` only returns direct children,
        real folder structures are commonly nested (issue #14 follow-up:
        a flat, direct-children-only listing missed every doc in a real
        test folder organized into subfolders). `max_depth` caps recursion
        depth, matching this project's "lightweight index" scope framing
        elsewhere (e.g. github_sync_max_files).
        """
        docs = []
        children = await self._list_folder_children(access_token, folder_id)
        for child in children:
            if child["mimeType"] == GOOGLE_DOC_MIME_TYPE:
                docs.append(child)
            elif child["mimeType"] == GOOGLE_FOLDER_MIME_TYPE and max_depth > 0:
                docs.extend(await self.list_folder_docs(access_token, child["id"], max_depth=max_depth - 1))
        return docs

    async def get_doc_content(self, access_token: str, file_id: str) -> str:
        """Fetches a Google Doc's structured body and flattens it to
        markdown-heading-style plain text (see `_flatten_docs_body`).
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GOOGLE_DOCS_API}/documents/{file_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            return _flatten_docs_body(resp.json())


google_drive_client = GoogleDriveClient()
