from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
import enum

Base = declarative_base()


class MediaType(str, enum.Enum):
    MOVIE = "movie"
    SERIES = "series"


class MediaStatus(str, enum.Enum):
    NEW = "new"
    PROCESSING = "processing"
    APPROVED = "approved"
    AVAILABLE = "available"
    IGNORED = "ignored"


class ScrapeStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSED = "processed"
    IGNORED = "ignored"
    ERROR = "error"


class ScrapedItem(Base):
    """
    Buffer table for raw data from Binged or other sources.
    This allows re-processing without re-scraping the web.
    """

    __tablename__ = "scraped_items"

    id = Column(Integer, primary_key=True, index=True)
    source_url = Column(String, unique=True, index=True, nullable=False)
    title = Column(String, index=True)
    year = Column(Integer, nullable=True)
    media_type = Column(String, index=True, nullable=True)
    platform = Column(String, nullable=True)
    streaming_date = Column(Date, nullable=True, index=True)

    # Use JSONB for PostgreSQL (faster indexing), fallback to JSON for SQLite
    raw_data = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)

    scrape_status = Column(String, default=ScrapeStatus.PENDING)
    error_message = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class MediaItem(Base):
    """
    The Clean Catalog.
    Contains enriched metadata (TMDB/IMDb) and is the source of truth for the UI.
    """

    __tablename__ = "media_items"

    id = Column(Integer, primary_key=True, index=True)

    # Metadata
    title = Column(String, index=True, nullable=False)
    year = Column(Integer, nullable=True)
    media_type = Column(String, nullable=False)  # 'movie' or 'series'
    language = Column(String, nullable=True, index=True)

    # IDs (Unique Constraints to prevent duplicates)
    tmdb_id = Column(Integer, unique=True, nullable=True, index=True)
    imdb_id = Column(String, unique=True, nullable=True, index=True)

    # Details
    overview = Column(String, nullable=True)
    poster_url = Column(String, nullable=True)
    backdrop_url = Column(String, nullable=True)

    # Use JSONB for PostgreSQL, fallback to JSON for SQLite
    genres = Column(JSON().with_variant(JSONB, "postgresql"), default=[])

    # Ingestion Source Info
    binged_url = Column(String, nullable=True)  # Link back to source if needed
    platform = Column(String, nullable=True)

    streaming_date = Column(Date, nullable=True, index=True)

    # App State
    status = Column(String, default=MediaStatus.NEW, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
