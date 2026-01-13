from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import event
from sqlalchemy.engine import Engine
import logging
from app.core.config import settings
from app.db.models import Base

logger = logging.getLogger(__name__)

# pool_pre_ping=True works for SQLite too; it checks if the connection is alive.
# check_same_thread=False is needed for SQLite with asyncio.
logger.debug(f"Creating database engine with URL: {settings.DATABASE_URL[:50]}...")

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
    connect_args=(
        {"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
    ),
)


# --- CRITICAL: Enable Foreign Keys for SQLite ---
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if "sqlite" in settings.DATABASE_URL:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


logger.info("Database engine created successfully")

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def init_db():
    """
    Creates database tables based on SQLAlchemy models.
    """
    logger.info("Initializing database tables...")
    async with engine.begin() as conn:
        # await conn.run_sync(Base.metadata.drop_all) # Uncomment to reset DB
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialized successfully")


async def get_db():
    logger.debug("Creating new database session")
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            logger.debug("Closing database session")
            await session.close()
