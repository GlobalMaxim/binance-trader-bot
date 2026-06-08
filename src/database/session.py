from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def create_session_factory(dsn: str) -> async_sessionmaker[AsyncSession]:
    """Return an async session factory from a standard postgresql:// DSN."""
    async_dsn = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(async_dsn, echo=False)
    return async_sessionmaker(engine, expire_on_commit=False)
