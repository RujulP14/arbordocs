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
        if user is None:
            # First-ever login from this identity — create a pending row
            # (ADR-0006) rather than rejecting with nothing to show for it;
            # an existing admin can flip `verified` once they recognize the
            # request.
            user = User(github_login=github_login, email=identity.get("email"))
            db.add(user)
            await db.commit()

        if not (user.verified or user.is_admin):
            return RedirectResponse(f"/auth/github/pending?login={github_login}")

    request.session["user_id"] = str(user.id)
    return RedirectResponse("/projects")


@router.get("/pending")
async def pending(login: str = "") -> dict:
    detail = "Your ArborDocs account has been created and is awaiting approval."
    if login:
        detail += f" GitHub identity received: '{login}'."
    detail += " Ask an existing admin to verify your account."
    return {"detail": detail}


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/auth/github/login", status_code=303)
