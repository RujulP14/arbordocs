import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


class FakeEmbedder:
    """Deterministic fake embedder for tests — no real model download/load.

    Encodes a string as a similarity-preserving toy vector: shares a fixed
    "concept" vocabulary so semantically-tagged test sentences produce high
    cosine similarity with each other and low similarity with unrelated ones,
    without needing a real sentence-transformers model in CI.
    """

    def __init__(self, concept_map: dict[str, list[float]] | None = None) -> None:
        self.concept_map = concept_map or {}

    def embed(self, text: str) -> list[float]:
        for keyword, vector in self.concept_map.items():
            if keyword in text.lower():
                return vector
        return [0.0] * 8


@pytest.fixture
def fake_embedder():
    return FakeEmbedder(
        concept_map={
            "postgres": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "pagination": [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "unrelated": [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        }
    )
