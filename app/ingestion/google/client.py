import logging

import httpx

from app.config import settings

logger = logging.getLogger("arbordocs.google_client")

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

# Same style set, as a numeric level (lower = higher/outer heading) — used
# by find_section_range to decide where a section ends: at the next
# heading of equal-or-higher level, mirroring parse_doc_sections' own
# next-heading-or-EOF boundary logic but against live structural data.
_HEADING_STYLE_LEVEL = {
    "HEADING_1": 1,
    "HEADING_2": 2,
    "HEADING_3": 3,
    "HEADING_4": 4,
    "HEADING_5": 5,
    "HEADING_6": 6,
}


def _paragraph_text(paragraph: dict) -> str:
    return "".join(run.get("textRun", {}).get("content", "") for run in paragraph.get("elements", [])).strip()


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
        # Scope expanded for issue #26 (Drive piece 2) to include Docs write
        # access alongside piece 1's read-only listing/indexing scope —
        # already-connected installations' stored refresh tokens predate
        # this and won't carry the new scope, so they need reconnecting
        # (re-running this OAuth flow) before apply-to-Drive will work.
        scope = "https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/documents"
        return (
            "https://accounts.google.com/o/oauth2/v2/auth"
            f"?client_id={settings.google_client_id}"
            f"&redirect_uri={redirect_uri}"
            "&response_type=code"
            "&access_type=offline"
            "&prompt=consent"
            f"&scope={scope}"
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

    async def find_section_range(
        self, access_token: str, file_id: str, heading_text: str
    ) -> tuple[int, int] | None:
        """Re-fetches the doc's raw structured body (not the flattened
        string `get_doc_content` returns) and locates the live character-
        offset range of the section whose heading matches `heading_text`
        exactly (issue #26, Drive piece 2).

        This is always called fresh, immediately before an apply — never
        cached or persisted — because Docs API writes need indices into
        the *current* document state, and any edit made upstream of
        drafting would silently invalidate a stale range. Returns None
        (fail closed) if no paragraph's heading text matches exactly,
        which the caller must treat as "can't confidently locate the
        section, don't write."

        The returned range spans from the matching heading's start to the
        start of the next heading of equal-or-higher level (or end of
        document) — the same next-heading-or-EOF boundary
        `app.pipeline.github_index.parse_doc_sections` uses, just computed
        against live structural paragraphs instead of a markdown string.
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GOOGLE_DOCS_API}/documents/{file_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            document = resp.json()

        paragraphs = []
        for element in document.get("body", {}).get("content", []):
            paragraph = element.get("paragraph")
            if paragraph is None:
                continue
            style = paragraph.get("paragraphStyle", {}).get("namedStyleType", "")
            level = _HEADING_STYLE_LEVEL.get(style)
            if level is None:
                continue
            paragraphs.append(
                {
                    "level": level,
                    "text": _paragraph_text(paragraph),
                    "startIndex": element["startIndex"],
                }
            )

        match_index = next((i for i, p in enumerate(paragraphs) if p["text"] == heading_text.strip()), None)
        logger.warning(
            "find_section_range: file=%s looking_for=%r paragraphs_found=%r",
            file_id,
            heading_text.strip(),
            [p["text"] for p in paragraphs],
        )
        if match_index is None:
            return None

        match = paragraphs[match_index]
        # The Docs API rejects a deleteContentRange that reaches the body's
        # very last character — the document's terminal newline can never
        # be deleted — so a section running to end-of-document stops one
        # character short of it, rather than at the last paragraph's own
        # endIndex.
        end_index = document["body"]["content"][-1]["endIndex"] - 1
        for later in paragraphs[match_index + 1 :]:
            if later["level"] <= match["level"]:
                end_index = later["startIndex"]
                break

        return match["startIndex"], end_index

    async def apply_edit(
        self, access_token: str, file_id: str, start_index: int, end_index: int, new_content: str
    ) -> None:
        """Replaces the live range [start_index, end_index) with
        `new_content` via a single `documents.batchUpdate` call —
        `deleteContentRange` immediately followed by `insertText` at the
        range's start, both in one request so the Docs API applies them
        atomically (in-order within a single batchUpdate), avoiding a
        partial-delete-then-failed-insert state.
        """
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{GOOGLE_DOCS_API}/documents/{file_id}:batchUpdate",
                headers={"Authorization": f"Bearer {access_token}"},
                json={
                    "requests": [
                        {"deleteContentRange": {"range": {"startIndex": start_index, "endIndex": end_index}}},
                        {
                            "insertText": {
                                "location": {"index": start_index},
                                "text": new_content,
                            }
                        },
                    ]
                },
            )
            resp.raise_for_status()


google_drive_client = GoogleDriveClient()
