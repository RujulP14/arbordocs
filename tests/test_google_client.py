from app.config import settings
from app.ingestion.google import client as google_client


def test_oauth_authorize_url_includes_client_id_state_and_scope(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "client-abc")
    client = google_client.GoogleDriveClient()
    url = client.oauth_authorize_url(redirect_uri="https://example.com/cb", state="xyz")
    assert "client_id=client-abc" in url
    assert "redirect_uri=https://example.com/cb" in url
    assert "state=xyz" in url
    assert "access_type=offline" in url
    assert "drive.readonly" in url


def test_flatten_docs_body_renders_headings_as_markdown():
    document = {
        "body": {
            "content": [
                {
                    "paragraph": {
                        "elements": [{"textRun": {"content": "API Guidelines\n"}}],
                        "paragraphStyle": {"namedStyleType": "HEADING_1"},
                    }
                },
                {
                    "paragraph": {
                        "elements": [{"textRun": {"content": "Overview text.\n"}}],
                        "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                    }
                },
                {
                    "paragraph": {
                        "elements": [{"textRun": {"content": "Pagination\n"}}],
                        "paragraphStyle": {"namedStyleType": "HEADING_2"},
                    }
                },
                {
                    "paragraph": {
                        "elements": [{"textRun": {"content": "Use cursor pagination.\n"}}],
                        "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                    }
                },
            ]
        }
    }

    result = google_client._flatten_docs_body(document)

    assert result == ("# API Guidelines\nOverview text.\n## Pagination\nUse cursor pagination.")


def test_flatten_docs_body_returns_empty_string_for_empty_document():
    assert google_client._flatten_docs_body({"body": {"content": []}}) == ""


def test_flatten_docs_body_ignores_non_paragraph_elements():
    document = {
        "body": {
            "content": [
                {"sectionBreak": {}},
                {
                    "paragraph": {
                        "elements": [{"textRun": {"content": "Just text.\n"}}],
                        "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                    }
                },
            ]
        }
    }

    result = google_client._flatten_docs_body(document)

    assert result == "Just text."


async def test_list_folder_docs_recurses_into_subfolders(monkeypatch):
    """A real Drive folder had every doc nested one level down — Drive v3's
    files.list only returns direct children, so list_folder_docs must
    recurse into subfolders to find them (issue #14 follow-up)."""
    client = google_client.GoogleDriveClient()

    children_by_folder = {
        "root": [
            {"id": "doc-1", "name": "Top-level Doc", "mimeType": google_client.GOOGLE_DOC_MIME_TYPE},
            {"id": "sub-1", "name": "Subfolder", "mimeType": google_client.GOOGLE_FOLDER_MIME_TYPE},
        ],
        "sub-1": [
            {"id": "doc-2", "name": "Nested Doc", "mimeType": google_client.GOOGLE_DOC_MIME_TYPE},
        ],
    }

    async def fake_list_folder_children(access_token, folder_id):
        return children_by_folder[folder_id]

    monkeypatch.setattr(client, "_list_folder_children", fake_list_folder_children)

    docs = await client.list_folder_docs("fake-token", "root")

    names = {d["name"] for d in docs}
    assert names == {"Top-level Doc", "Nested Doc"}


async def test_list_folder_docs_respects_max_depth(monkeypatch):
    client = google_client.GoogleDriveClient()

    async def fake_list_folder_children(access_token, folder_id):
        # Each folder contains one subfolder, infinitely — max_depth must
        # actually stop the recursion or this test hangs/recurses forever.
        return [
            {"id": f"{folder_id}-child", "name": "sub", "mimeType": google_client.GOOGLE_FOLDER_MIME_TYPE}
        ]

    monkeypatch.setattr(client, "_list_folder_children", fake_list_folder_children)

    docs = await client.list_folder_docs("fake-token", "root", max_depth=2)

    assert docs == []


async def test_list_folders_merges_owned_and_shared_deduplicated(monkeypatch):
    """A real Drive folder ("Rujul Dudhat FTE") only appeared under
    sharedWithMe, not under owned-by-me — list_folders must query both and
    merge, or a shared team folder is invisible to the connect flow
    (issue #14 follow-up)."""
    client = google_client.GoogleDriveClient()
    call_queries = []

    class FakeResponse:
        def __init__(self, files):
            self._files = files

        def raise_for_status(self):
            pass

        def json(self):
            return {"files": self._files}

    class FakeHttpxClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers, params):
            call_queries.append(params["q"])
            if "sharedWithMe" in params["q"]:
                return FakeResponse([{"id": "shared-1", "name": "Shared Folder"}])
            return FakeResponse([{"id": "owned-1", "name": "Owned Folder"}])

    monkeypatch.setattr(google_client.httpx, "AsyncClient", lambda: FakeHttpxClient())

    folders = await client.list_folders("fake-token")

    names = {f["name"] for f in folders}
    assert names == {"Owned Folder", "Shared Folder"}
    assert any("sharedWithMe" in q for q in call_queries)
    assert any("'me' in owners" in q for q in call_queries)


def _heading_paragraph(text: str, style: str, start_index: int, end_index: int) -> dict:
    return {
        "startIndex": start_index,
        "endIndex": end_index,
        "paragraph": {
            "elements": [{"textRun": {"content": f"{text}\n"}}],
            "paragraphStyle": {"namedStyleType": style},
        },
    }


class _FakeGetResponse:
    def __init__(self, document: dict) -> None:
        self._document = document

    def raise_for_status(self):
        pass

    def json(self):
        return self._document


class _FakeGetClient:
    def __init__(self, document: dict) -> None:
        self._document = document

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, headers):
        return _FakeGetResponse(self._document)


async def test_find_section_range_spans_to_next_equal_or_higher_heading(monkeypatch):
    """Two sibling H2 sections — the first section's range must stop at
    the second heading's startIndex, not run into it."""
    document = {
        "body": {
            "content": [
                _heading_paragraph("Pagination", "HEADING_2", 1, 16),
                {
                    "startIndex": 16,
                    "endIndex": 40,
                    "paragraph": {
                        "elements": [{"textRun": {"content": "Use cursor pagination.\n"}}],
                        "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                    },
                },
                _heading_paragraph("Rate limits", "HEADING_2", 40, 56),
                {
                    "startIndex": 56,
                    "endIndex": 80,
                    "paragraph": {
                        "elements": [{"textRun": {"content": "100 requests per minute.\n"}}],
                        "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                    },
                },
            ]
        }
    }
    monkeypatch.setattr(google_client.httpx, "AsyncClient", lambda: _FakeGetClient(document))
    client = google_client.GoogleDriveClient()

    result = await client.find_section_range("fake-token", "file-1", "Pagination")

    assert result == (1, 40)


async def test_find_section_range_stops_short_of_documents_terminal_newline(monkeypatch):
    """Real Docs API bug hit during live smoke testing (issue #26): a
    section running to end-of-document must NOT include the document
    body's very last character — deleteContentRange rejects a range that
    reaches the doc's terminal newline with a 400."""
    document = {
        "body": {
            "content": [
                _heading_paragraph("API Guidelines", "HEADING_1", 1, 16),
                {
                    "startIndex": 16,
                    "endIndex": 178,
                    "paragraph": {
                        "elements": [{"textRun": {"content": "The API uses offset-based pagination.\n"}}],
                        "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                    },
                },
            ]
        }
    }
    monkeypatch.setattr(google_client.httpx, "AsyncClient", lambda: _FakeGetClient(document))
    client = google_client.GoogleDriveClient()

    result = await client.find_section_range("fake-token", "file-1", "API Guidelines")

    assert result == (1, 177)


async def test_find_section_range_returns_none_when_heading_not_found(monkeypatch):
    document = {"body": {"content": [_heading_paragraph("Something Else", "HEADING_1", 1, 20)]}}
    monkeypatch.setattr(google_client.httpx, "AsyncClient", lambda: _FakeGetClient(document))
    client = google_client.GoogleDriveClient()

    result = await client.find_section_range("fake-token", "file-1", "Nonexistent Section")

    assert result is None


async def test_apply_edit_issues_single_batch_update_with_delete_then_insert(monkeypatch):
    calls = []

    class FakePostResponse:
        def raise_for_status(self):
            pass

    class FakePostClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers, json):
            calls.append((url, json))
            return FakePostResponse()

    monkeypatch.setattr(google_client.httpx, "AsyncClient", lambda: FakePostClient())
    client = google_client.GoogleDriveClient()

    await client.apply_edit("fake-token", "file-1", 1, 177, "New section content.")

    assert len(calls) == 1
    url, body = calls[0]
    assert url.endswith("file-1:batchUpdate")
    requests = body["requests"]
    assert requests[0]["deleteContentRange"]["range"] == {"startIndex": 1, "endIndex": 177}
    assert requests[1]["insertText"] == {"location": {"index": 1}, "text": "New section content."}
