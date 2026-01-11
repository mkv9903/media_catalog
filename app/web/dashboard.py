from fastapi import APIRouter, Request, Depends, Query, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import logging
from app.db.database import get_db
from app.db.models import MediaItem, MediaStatus, MediaType
from app.services.metadata import MetadataService
from app.services.db import get_filtered_items  # Import shared logic

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# --- HTML Page Endpoints ---


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Renders the main dashboard page."""
    logger.debug("Rendering main dashboard page")
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "current_status": "all",
            "current_type": "all",
            "current_q": "",
        },
    )


@router.get("/dashboard/items", response_class=HTMLResponse)
async def get_items_html(
    request: Request,
    status: str = Query("all"),
    media_type: str = Query("all"),
    q: str = Query(""),
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Returns the HTML partial for the media grid with filtering and search."""

    # Delegate to shared service
    # Note: 'offset' in HTMX is mapped to 'skip' in logic
    items, total = await get_filtered_items(
        db=db,
        skip=offset,
        limit=limit,
        status=status,
        media_type=media_type,
        q=q,
        # We can also pass genres/platforms here later if we add UI filters for them
    )

    logger.info(
        f"Dashboard: Returning {len(items)} items for HTML grid (offset={offset}, limit={limit})"
    )

    next_offset = offset + limit if len(items) == limit else None

    return templates.TemplateResponse(
        "partials/media_grid.html",
        {
            "request": request,
            "items": items,
            "next_offset": next_offset,
            "current_status": status,
            "current_type": media_type,
            "current_q": q,
        },
    )


@router.get("/dashboard/item/{item_id}", response_class=HTMLResponse)
async def get_item_detail(
    item_id: int, request: Request, db: AsyncSession = Depends(get_db)
):
    """Returns the item detail view."""
    logger.debug(f"Fetching item detail HTML for ID: {item_id}")
    result = await db.execute(select(MediaItem).where(MediaItem.id == item_id))
    item = result.scalar_one_or_none()

    if not item:
        logger.warning(f"Item detail not found for ID: {item_id}")
        return HTMLResponse("Item not found", status_code=404)

    logger.info(f"Rendering detail view for item: {item.title} (ID: {item_id})")
    return templates.TemplateResponse(
        "partials/detail_modal.html",
        {"request": request, "item": item},
    )


# --- EDIT / DELETE / SMART SYNC Endpoints ---


@router.get("/dashboard/item/{item_id}/edit", response_class=HTMLResponse)
async def get_edit_form(
    item_id: int, request: Request, db: AsyncSession = Depends(get_db)
):
    """Returns the Edit Form partial pre-filled with DB data."""
    logger.debug(f"Fetching edit form HTML for item ID: {item_id}")
    result = await db.execute(select(MediaItem).where(MediaItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        logger.warning(f"Edit form not found for item ID: {item_id}")
        return HTMLResponse("Not found")
    logger.info(f"Rendering edit form for item: {item.title} (ID: {item_id})")
    return templates.TemplateResponse(
        "partials/edit_form.html", {"request": request, "item": item}
    )


@router.post("/dashboard/item/{item_id}/sync", response_class=HTMLResponse)
async def sync_item_metadata(
    item_id: int,
    request: Request,
    id_type: str = Form(...),
    tmdb_id: str = Form(None),
    imdb_id: str = Form(None),
    media_type: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Fetches fresh metadata and returns updated form without saving."""
    logger.debug(
        f"Syncing metadata for item {item_id} via web interface: id_type={id_type}, tmdb_id={tmdb_id}, imdb_id={imdb_id}, media_type={media_type}"
    )
    meta_service = MetadataService()
    # Ensure media_type string is valid if using Enum
    m_type = (
        MediaType(media_type) if media_type in [m.value for m in MediaType] else None
    )

    result = await db.execute(select(MediaItem).where(MediaItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        logger.warning(f"Cannot sync metadata for item {item_id}: not found")
        return HTMLResponse("Item not found")

    match_data = None
    try:
        if id_type == "imdb" and imdb_id:
            logger.debug(f"Fetching metadata by IMDB ID: {imdb_id}")
            match_data = await meta_service.get_details_by_imdb(imdb_id.strip(), m_type)
        elif id_type == "tmdb" and tmdb_id:
            logger.debug(f"Fetching metadata by TMDB ID: {tmdb_id}")
            match_data = await meta_service.get_details_by_tmdb_id(int(tmdb_id), m_type)
    except (ValueError, TypeError) as e:
        logger.warning(f"Sync ID conversion error for item {item_id}: {e}")

    if match_data:
        item.tmdb_id = match_data.get("tmdb_id")
        item.imdb_id = match_data.get("imdb_id")
        item.title = match_data.get("title")
        item.overview = match_data.get("overview")
        item.year = match_data.get("year")
        item.poster_url = match_data.get("poster_url")
        item.backdrop_url = match_data.get("backdrop_url")
        if m_type:
            item.media_type = m_type.value
        logger.info(
            f"Successfully synced metadata for item: {item.title} (ID: {item_id})"
        )
    else:
        logger.warning(f"No metadata match found for item {item_id}")

    return templates.TemplateResponse(
        "partials/edit_form.html", {"request": request, "item": item}
    )


@router.put("/dashboard/item/{item_id}", response_class=HTMLResponse)
async def update_item(
    item_id: int,
    request: Request,
    title: str = Form(...),
    year: int = Form(...),
    tmdb_id: str = Form(None),
    imdb_id: str = Form(None),
    media_type: str = Form(...),
    status: str = Form(...),
    poster_url: str = Form(None),
    backdrop_url: str = Form(None),
    overview: str = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Saves edited details."""
    logger.debug(f"Updating item {item_id} via web interface with title: {title}")
    stmt = select(MediaItem).where(MediaItem.id == item_id)
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()

    if not item:
        logger.warning(f"Cannot update item {item_id}: not found")
        return HTMLResponse("Error: Item not found")

    item.title = title
    item.year = year
    item.media_type = media_type
    item.status = status
    item.tmdb_id = int(tmdb_id) if tmdb_id and tmdb_id.strip() else None
    item.imdb_id = imdb_id.strip() if imdb_id else None
    item.poster_url = poster_url
    item.backdrop_url = backdrop_url
    item.overview = overview

    await db.commit()
    logger.info(
        f"Successfully updated item via web interface: {item.title} (ID: {item_id})"
    )
    return await get_item_detail(item_id, request, db)


@router.delete("/dashboard/item/{item_id}", response_class=HTMLResponse)
async def delete_item(item_id: int, db: AsyncSession = Depends(get_db)):
    """Deletes item and triggers a grid refresh."""
    logger.debug(f"Deleting item {item_id} via web interface")
    stmt = select(MediaItem).where(MediaItem.id == item_id)
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()
    if item:
        await db.delete(item)
        await db.commit()
        logger.info(
            f"Successfully deleted item via web interface: {item.title} (ID: {item_id})"
        )
    else:
        logger.warning(f"Cannot delete item {item_id}: not found")
    return Response(content="", headers={"HX-Trigger": "refreshGrid"})
