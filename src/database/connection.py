import asyncpg


async def create_pool(dsn: str) -> asyncpg.Pool:
    """Create an asyncpg connection pool. Schema is managed by Alembic."""
    return await asyncpg.create_pool(dsn)
