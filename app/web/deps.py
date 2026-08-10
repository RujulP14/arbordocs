import uuid

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.session import get_db


def _has_access(user: User) -> bool:
    """Same gate as auth callback session creation: verified OR admin."""
    return user.verified or user.is_admin


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = await db.get(User, uuid.UUID(user_id))
    if user is None or not _has_access(user):
        # Drop stale cookies after de-verify / delete so a known session id
        # cannot keep calling require_login routes.
        request.session.clear()
        return None
    return user


async def require_login(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """Any authenticated user, admin or not — for surfaces like the portal
    that don't require admin privileges, just a real session.

    Re-checks `verified`/`is_admin` on every request (not only at login).
    """
    user = await get_current_user(request, db)
    if user is None:
        raise HTTPException(status_code=303, headers={"Location": "/auth/github/login"})
    return user


async def require_admin(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    user = await require_login(request, db)
    if not user.is_admin:
        raise HTTPException(status_code=303, headers={"Location": "/auth/github/login"})
    return user
