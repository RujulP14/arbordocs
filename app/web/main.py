from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.web import (
    auth,
    decisions,
    integrations_discord,
    integrations_github,
    integrations_google,
    marketing,
    portal,
    projects,
)

app = FastAPI(title="ArborDocs")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)

app.mount("/static", StaticFiles(directory="app/web/static"), name="static")

app.include_router(marketing.router)
app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(integrations_github.router)
app.include_router(integrations_discord.router)
app.include_router(integrations_google.router)
app.include_router(decisions.router)
app.include_router(portal.router)
