"""One-time bootstrap: insert the first admin user (ADR-0006).

Usage:
    uv run python -m scripts.seed_admin --github-login octocat [--email a@b.com]

Run this once per deployment, before the first login attempt. Every admin
added after this can go through a future in-app invite flow (not built yet);
this script exists only to solve the chicken-and-egg problem of getting the
very first admin into a `users` table that nothing else can write to yet.
"""

import argparse
import asyncio

from sqlalchemy import select

from app.db.models import User
from app.db.session import async_session


async def seed_admin(github_login: str, email: str | None) -> None:
    async with async_session() as session:
        existing = await session.scalar(select(User).where(User.github_login == github_login))
        if existing:
            existing.is_admin = True
            existing.verified = True
            if email:
                existing.email = email
            await session.commit()
            print(f"Updated existing user '{github_login}' -> is_admin=True, verified=True")
            return

        user = User(github_login=github_login, email=email, is_admin=True, verified=True)
        session.add(user)
        await session.commit()
        print(f"Created admin user '{github_login}' (id={user.id})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-login", required=True, help="GitHub username of the first admin")
    parser.add_argument("--email", default=None, help="Optional email to store alongside the user")
    args = parser.parse_args()
    asyncio.run(seed_admin(args.github_login, args.email))


if __name__ == "__main__":
    main()
