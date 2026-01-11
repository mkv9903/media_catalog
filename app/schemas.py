from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional, Generic, TypeVar
from datetime import date, datetime
from app.db.models import MediaType, MediaStatus

# --- Generic Response Wrappers ---

T = TypeVar("T")


class ResponseModel(BaseModel, Generic[T]):
    """Standard wrapper for single object responses."""

    data: T
    message: Optional[str] = None


class MetaData(BaseModel):
    """Metadata for list responses (pagination, counts)."""

    total: int
    limit: Optional[int] = None
    skip: Optional[int] = None
    page: Optional[int] = None

    # Custom fields for specific contexts
    cached_count: Optional[int] = None
    total_found: Optional[int] = None


class ListResponseModel(BaseModel, Generic[T]):
    """Standard wrapper for list responses."""

    data: List[T]
    meta: Optional[MetaData] = None


# --- Media Item Schemas ---


class MediaItemBase(BaseModel):
    """
    Base schema with validation removed to support messy scraped data.
    URL fields are strings to prevent validation errors on malformed links.
    """

    title: str
    year: Optional[int] = None
    media_type: MediaType
    status: Optional[MediaStatus] = MediaStatus.NEW
    poster_url: Optional[str] = None
    backdrop_url: Optional[str] = None
    overview: Optional[str] = None
    language: Optional[str] = None
    platform: Optional[str] = None
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    genres: List[str] = []
    binged_url: Optional[str] = None


class MediaItemUpdate(BaseModel):
    """Used for PATCH requests - all fields optional and unvalidated"""

    title: Optional[str] = None
    year: Optional[int] = None
    media_type: Optional[MediaType] = None
    status: Optional[MediaStatus] = None
    poster_url: Optional[str] = None
    backdrop_url: Optional[str] = None
    overview: Optional[str] = None
    language: Optional[str] = None
    platform: Optional[str] = None
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    genres: Optional[List[str]] = None
    binged_url: Optional[str] = None


class MediaItemResponse(MediaItemBase):
    """Used for GET responses"""

    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    streaming_date: Optional[date] = None

    model_config = ConfigDict(from_attributes=True)


# --- Search Result Schema ---


class SearchStreamResult(BaseModel):
    """Schema for individual stream results found via search."""

    filename: str
    size: str
    quality: str
    codec: str
    audio: str
    languages: str
    subtitles: Optional[str] = "Unknown"
    source: str
    info_hash: str


# --- Action Schemas ---


class SyncRequest(BaseModel):
    id_type: str  # 'tmdb' or 'imdb'
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    media_type: MediaType
