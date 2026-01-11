from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import cast, String, or_
from typing import Optional
import logging

from app.db.database import get_db
from app.db.models import MediaItem, MediaStatus, MediaType
from app.core.exceptions import ItemNotFoundError, ExternalApiError
from app.schemas import (
    MediaItemResponse,
    MediaItemUpdate,
    SyncRequest,
    ListResponseModel,
    ResponseModel,
    MetaData,
)
from app.services.metadata import MetadataService
from app.services.db import get_filtered_items  # Import shared logic

logger = logging.getLogger(__name__)

router = APIRouter()

# --- Media Items (Read) ---


@router.get("/items", response_model=ListResponseModel[MediaItemResponse])
async def list_items(
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
    media_type: Optional[str] = None,
    language: Optional[str] = None,
    platform: Optional[str] = None,
    genres: Optional[str] = None,
    q: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """List all media items with filtering and search."""

    # Delegate to shared service
    items, total = await get_filtered_items(
        db=db,
        skip=skip,
        limit=limit,
        status=status,
        media_type=media_type,
        language=language,
        platform=platform,
        genres=genres,
        q=q,
    )

    logger.info(f"API: Returning {len(items)} items (skip={skip}, limit={limit})")

    return ListResponseModel(
        data=items, meta=MetaData(total=total, limit=limit, skip=skip)
    )


@router.get("/items/{item_id}", response_model=ResponseModel[MediaItemResponse])
async def get_item(item_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single media item by ID."""
    logger.debug(f"Fetching item with ID: {item_id}")
    stmt = select(MediaItem).where(MediaItem.id == item_id)
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()
    if not item:
        logger.warning(f"Item with ID {item_id} not found")
        raise ItemNotFoundError(item_id)
    logger.info(f"Successfully retrieved item: {item.title} (ID: {item_id})")
    return ResponseModel(data=item)


# --- Media Items (Write) ---


@router.post("/items/{item_id}", response_model=ResponseModel[MediaItemResponse])
async def update_item(
    item_id: int, update_data: MediaItemUpdate, db: AsyncSession = Depends(get_db)
):
    """Update details of a media item."""
    logger.debug(
        f"Updating item {item_id} with data: {update_data.dict(exclude_unset=True)}"
    )
    stmt = select(MediaItem).where(MediaItem.id == item_id)
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()

    if not item:
        logger.warning(f"Cannot update item {item_id}: not found")
        raise ItemNotFoundError(item_id)

    # Update fields - only update provided fields
    if update_data.title is not None:
        item.title = update_data.title
    if update_data.year is not None:
        item.year = update_data.year
    if update_data.media_type is not None:
        item.media_type = update_data.media_type.value
    if update_data.status is not None:
        item.status = update_data.status.value
    if update_data.tmdb_id is not None:
        item.tmdb_id = update_data.tmdb_id
    if update_data.imdb_id is not None:
        item.imdb_id = update_data.imdb_id
    if update_data.poster_url is not None:
        item.poster_url = (
            str(update_data.poster_url) if update_data.poster_url else None
        )
    if update_data.backdrop_url is not None:
        item.backdrop_url = (
            str(update_data.backdrop_url) if update_data.backdrop_url else None
        )
    if update_data.overview is not None:
        item.overview = update_data.overview
    if update_data.language is not None:
        item.language = update_data.language
    if update_data.platform is not None:
        item.platform = update_data.platform
    if update_data.genres is not None:
        item.genres = update_data.genres
    if update_data.binged_url is not None:
        item.binged_url = (
            str(update_data.binged_url) if update_data.binged_url else None
        )

    await db.commit()
    await db.refresh(item)
    logger.info(f"Successfully updated item: {item.title} (ID: {item_id})")
    return ResponseModel(data=item)


@router.delete("/items/{item_id}")
async def delete_item(item_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a media item."""
    logger.debug(f"Deleting item with ID: {item_id}")
    stmt = select(MediaItem).where(MediaItem.id == item_id)
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()

    if not item:
        logger.warning(f"Cannot delete item {item_id}: not found")
        raise ItemNotFoundError(item_id)

    await db.delete(item)
    await db.commit()
    logger.info(f"Successfully deleted item: {item.title} (ID: {item_id})")
    return {"status": "deleted", "id": item_id}


@router.post("/items/{item_id}/sync", response_model=ResponseModel[MediaItemResponse])
async def sync_metadata(
    item_id: int, sync_req: SyncRequest, db: AsyncSession = Depends(get_db)
):
    """Fetch fresh metadata from TMDB/IMDb and update the item."""
    logger.debug(f"Syncing metadata for item {item_id} with request: {sync_req.dict()}")
    stmt = select(MediaItem).where(MediaItem.id == item_id)
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()

    if not item:
        logger.warning(f"Cannot sync metadata for item {item_id}: not found")
        raise ItemNotFoundError(item_id)

    meta_service = MetadataService()
    match_data = None

    try:
        if sync_req.id_type == "imdb" and sync_req.imdb_id:
            logger.debug(f"Fetching metadata by IMDB ID: {sync_req.imdb_id}")
            match_data = await meta_service.get_details_by_imdb(
                sync_req.imdb_id, sync_req.media_type
            )
        elif sync_req.id_type == "tmdb" and sync_req.tmdb_id:
            logger.debug(f"Fetching metadata by TMDB ID: {sync_req.tmdb_id}")
            match_data = await meta_service.get_details_by_tmdb_id(
                sync_req.tmdb_id, sync_req.media_type
            )
    except Exception as e:
        logger.error(f"Failed to fetch metadata for item {item_id}: {str(e)}")
        raise ExternalApiError("Metadata Provider", str(e))

    if not match_data:
        logger.warning(
            f"No metadata match found for item {item_id} with request: {sync_req.dict()}"
        )
        raise HTTPException(status_code=404, detail="No metadata match found")

    # Apply updates
    item.tmdb_id = match_data.get("tmdb_id")
    item.imdb_id = match_data.get("imdb_id")
    item.title = match_data.get("title")
    item.overview = match_data.get("overview")
    item.year = match_data.get("year")
    item.poster_url = match_data.get("poster_url")
    item.backdrop_url = match_data.get("backdrop_url")
    item.media_type = sync_req.media_type.value

    await db.commit()
    await db.refresh(item)
    logger.info(f"Successfully synced metadata for item: {item.title} (ID: {item_id})")
    return ResponseModel(data=item)
