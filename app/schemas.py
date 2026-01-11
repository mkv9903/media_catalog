from pydantic import BaseModel, HttpUrl, ConfigDict, Field, field_validator
from typing import List, Optional, Generic, TypeVar, Any
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
    title: str = Field(..., min_length=1, max_length=500)
    year: Optional[int] = Field(None, ge=1800, le=2100)
    media_type: MediaType
    status: Optional[MediaStatus] = MediaStatus.NEW
    poster_url: Optional[HttpUrl] = None
    backdrop_url: Optional[HttpUrl] = None
    overview: Optional[str] = Field(None, max_length=2000)
    language: Optional[str] = Field(None, min_length=2, max_length=5)
    platform: Optional[str] = Field(None, max_length=100)
    tmdb_id: Optional[int] = Field(None, gt=0)
    imdb_id: Optional[str] = Field(None, pattern=r"^tt\d{7,8}$")
    genres: List[str] = Field(default_factory=list)
    binged_url: Optional[HttpUrl] = None


class MediaItemUpdate(BaseModel):
    """Used for PATCH requests - all fields optional"""

    title: Optional[str] = Field(None, min_length=1, max_length=500)
    year: Optional[int] = Field(None, ge=1800, le=2100)
    media_type: Optional[MediaType] = None
    status: Optional[MediaStatus] = None
    poster_url: Optional[HttpUrl] = None
    backdrop_url: Optional[HttpUrl] = None
    overview: Optional[str] = Field(None, max_length=2000)
    language: Optional[str] = Field(None, min_length=2, max_length=5)
    platform: Optional[str] = Field(None, max_length=100)
    tmdb_id: Optional[int] = Field(None, gt=0)
    imdb_id: Optional[str] = Field(None, pattern=r"^tt\d{7,8}$")
    genres: Optional[List[str]] = None
    binged_url: Optional[HttpUrl] = None


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
