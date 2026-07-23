import uuid

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.session import get_db


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return await db.get(User, uuid.UUID(user_id))


async def require_login(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """Any authenticated user, admin or not — for surfaces like the portal
    that don't require admin privileges, just a real session.
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
