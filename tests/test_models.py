from datetime import UTC

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, DiscordGuild, GitHubInstallation, Message, Project, ProjectChannel, User


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


async def test_project_scoping_end_to_end(db_session):
    admin = User(github_login="octocat", is_admin=True)
    db_session.add(admin)
    await db_session.flush()

    project = Project(name="Test Project", created_by=admin.id)
    db_session.add(project)
    await db_session.flush()

    db_session.add(
        GitHubInstallation(project_id=project.id, installation_id="inst-1", repo_full_name="octo/repo")
    )

    guild = DiscordGuild(guild_id="guild-1", guild_name="Test Guild")
    db_session.add(guild)
    await db_session.flush()

    channel = ProjectChannel(
        project_id=project.id,
        discord_guild_id=guild.id,
        channel_id="chan-1",
        channel_name="general",
    )
    db_session.add(channel)
    await db_session.flush()

    from datetime import datetime

    db_session.add(
        Message(
            project_id=project.id,
            channel_id="chan-1",
            discord_message_id="msg-1",
            author_id="user-1",
            content="let's go with Postgres",
            created_at=datetime.now(UTC),
        )
    )
    await db_session.commit()

    stored = (await db_session.execute(Message.__table__.select())).mappings().all()
    assert len(stored) == 1
    assert stored[0]["project_id"] == project.id
