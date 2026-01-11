from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import logging
from app.core.config import settings
from app.db.models import Base  # Import Base to access metadata for table creation

logger = logging.getLogger(__name__)

# pool_pre_ping=True is critical for PostgreSQL.
# It checks if the connection is alive before using it, preventing "Closed Connection" errors.
logger.debug(f"Creating database engine with URL: {settings.DATABASE_URL[:50]}...")
engine = create_async_engine(
    settings.DATABASE_URL, echo=False, future=True, pool_pre_ping=True
)
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
