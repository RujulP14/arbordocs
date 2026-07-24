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
