from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional, Dict, Any
import logging

from app.db.database import get_db
from app.db.models import MediaItem, MediaStatus, MediaType

logger = logging.getLogger(__name__)

router = APIRouter()

MANIFEST = {
    "id": "org.mediaflow.local",
    "version": "1.0.0",
    "name": "MediaFlow Local",
    "description": "Serves your locally curated media library from MediaFlow.",
    "resources": ["catalog", "stream"],
    "types": ["movie", "series"],
    "catalogs": [
        {"type": "movie", "id": "mediaflow_catalog_movie", "name": "MediaFlow Movies"},
        {
            "type": "series",
            "id": "mediaflow_catalog_series",
            "name": "MediaFlow Series",
        },
    ],
    "idPrefixes": ["tt", "tmdb"],
}


@router.get("/manifest.json")
async def get_manifest():
    """
    Stremio Manifest Endpoint.
    Tells Stremio what this addon can do.
    """
    logger.debug("Serving Stremio manifest")
    return MANIFEST


@router.get("/catalog/{type}/{id}.json")
async def get_catalog(type: str, id: str, db: AsyncSession = Depends(get_db)):
    """
    Stremio Catalog Endpoint.
    Returns a list of 'MetaPreview' objects for the Home Screen.
    """
    logger.debug(f"Serving Stremio catalog for type: {type}, id: {id}")
    # 1. Validate Type
    if type not in ["movie", "series"]:
        logger.warning(f"Invalid catalog type requested: {type}")
        return {"metas": []}

    # 2. Query DB for Available Items
    # We only show items that are marked as AVAILABLE (cached) or APPROVED.
    # Adjust this filter based on what you want to show in Stremio.
    stmt = (
        select(MediaItem)
        .where(MediaItem.media_type == type)
        .where(MediaItem.status.in_([MediaStatus.AVAILABLE, MediaStatus.APPROVED]))
        .order_by(MediaItem.created_at.desc())
        .limit(100)  # Pagination logic can be added later if needed
    )

    result = await db.execute(stmt)
    items = result.scalars().all()
    logger.info(f"Found {len(items)} items for Stremio catalog type: {type}")

    # 3. Format for Stremio
    metas = []
    for item in items:
        # Stremio expects 'id' to be the IMDb ID (tt...) or a custom ID.
        # Since we use Cinemeta for metadata, we MUST provide the IMDb ID
        # so Stremio can link it correctly.
        stremio_id = item.imdb_id if item.imdb_id else f"tmdb:{item.tmdb_id}"

        if not stremio_id:
            logger.debug(f"Skipping item {item.id} ({item.title}): no valid Stremio ID")
            continue  # Skip items without standard IDs

        metas.append(
            {
                "id": stremio_id,
                "type": type,
                "name": item.title,
                "poster": item.poster_url,
                "description": item.overview,
            }
        )

    logger.debug(f"Returning {len(metas)} metas for Stremio catalog")
    return {"metas": metas}


@router.get("/stream/{type}/{id}.json")
async def get_streams(type: str, id: str, db: AsyncSession = Depends(get_db)):
    """
    Stremio Stream Endpoint.
    Returns a list of 'Stream' objects for a specific item.
    Currently a DUMMY implementation returning empty list.
    """
    logger.debug(
        f"Stream request for type: {type}, id: {id} (placeholder implementation)"
    )
    # Placeholder: Logic to fetch MediaLinks for this 'id' goes here later.
    return {"streams": []}
