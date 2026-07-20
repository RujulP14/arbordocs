import base64

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import settings
from app.ingestion.github import client as github_client


def _generate_test_key_b64() -> tuple[str, object]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return base64.b64encode(pem).decode("utf-8"), key.public_key()


def test_sign_app_jwt_shape(monkeypatch):
    key_b64, public_key = _generate_test_key_b64()
    monkeypatch.setattr(settings, "github_app_private_key_b64", key_b64)
    monkeypatch.setattr(settings, "github_app_id", "12345")

    token = github_client.sign_app_jwt()

    pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    decoded = jwt.decode(token, pem, algorithms=["RS256"])

    assert decoded["iss"] == "12345"
    assert decoded["exp"] > decoded["iat"]


def test_install_url_uses_configured_slug(monkeypatch):
    monkeypatch.setattr(settings, "github_app_slug", "arbordocs-test")
    client = github_client.GitHubAppClient()
    url = client.install_url(state="project-123")
    assert url == "https://github.com/apps/arbordocs-test/installations/new?state=project-123"


def test_oauth_authorize_url_includes_client_id_and_state(monkeypatch):
    monkeypatch.setattr(settings, "github_app_client_id", "client-abc")
    client = github_client.GitHubAppClient()
    url = client.oauth_authorize_url(redirect_uri="https://example.com/cb", state="xyz")
    assert "client_id=client-abc" in url
    assert "redirect_uri=https://example.com/cb" in url
    assert "state=xyz" in url
