import pytest
from httpx import ASGITransport, AsyncClient

from app.web.main import app
from app.web.privacy_policy import privacy_policy_html


async def test_privacy_page_is_public_and_renders_policy():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/privacy")

    assert resp.status_code == 200
    body = resp.text
    assert "Privacy Policy" in body
    assert "Last updated" in body
    assert "Rujul Dudhat" in body
    assert "prujul14@gmail.com" in body
    assert "Operator checklist" not in body
    assert 'href="/privacy"' in body


@pytest.mark.parametrize("path", ["/", "/pricing", "/support", "/privacy", "/auth/github/login"])
async def test_footer_renders_on_every_page(path):
    """The footer lives in base.html, so app pages get it too — not just marketing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(path)

    assert resp.status_code == 200
    body = resp.text
    assert '<footer class="footer">' in body
    assert 'href="/privacy"' in body
    assert ">Privacy<" in body


def test_privacy_policy_html_strips_operator_checklist():
    html = privacy_policy_html()
    assert "Privacy Policy" in html
    assert "Operator checklist" not in html
    assert "prujul14@gmail.com" in html
