import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.config import settings
from app.db.models import User
from app.db.session import async_session
from app.ingestion.github.client import github_app_client

router = APIRouter(prefix="/auth/github", tags=["auth"])


def _callback_url() -> str:
    return f"{settings.base_url}/auth/github/callback"


@router.get("/login")
async def login(request: Request) -> RedirectResponse:
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    url = github_app_client.oauth_authorize_url(redirect_uri=_callback_url(), state=state)
    return RedirectResponse(url)


@router.get("/callback")
async def callback(request: Request, code: str, state: str) -> RedirectResponse:
    expected_state = request.session.pop("oauth_state", None)
    if not expected_state or expected_state != state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    token_data = await github_app_client.exchange_oauth_code(code)
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="GitHub OAuth exchange failed")

    identity = await github_app_client.fetch_identity(access_token)
    github_login = identity["login"]

    async with async_session() as db:
        user = await db.scalar(select(User).where(User.github_login == github_login))

    if user is None or not user.is_admin:
        # No self-serve signup (ADR-0006) — unknown or non-admin identities are rejected.
        return RedirectResponse(f"/auth/github/denied?login={github_login}")

    request.session["user_id"] = str(user.id)
    return RedirectResponse("/projects")


@router.get("/denied")
async def denied(login: str = "") -> dict:
    detail = "This GitHub account is not registered as an ArborDocs admin."
    if login:
        detail += f" GitHub identity received: '{login}'."
    return {"detail": detail}


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/auth/github/login", status_code=303)
