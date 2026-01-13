from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, or_, cast, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from typing import Optional, List, Tuple
import logging
from app.db.models import MediaItem

logger = logging.getLogger(__name__)


async def get_filtered_items(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
    media_type: Optional[str] = None,
    language: Optional[str] = None,
    platform: Optional[str] = None,
    genres: Optional[str] = None,
    q: Optional[str] = None,
) -> Tuple[List[MediaItem], int]:
    """
    Shared business logic to filter and retrieve media items.
    """
    logger.debug(
        f"Filtering items via DB Service: skip={skip}, limit={limit}, status={status}, type={media_type}, q={q}"
    )

    stmt = select(MediaItem)
    count_stmt = select(func.count()).select_from(MediaItem)
    conditions = []

    # 1. Status (Exact Match, supports comma-separated)
    if status and status != "all":
        status_list = [s.strip() for s in status.split(",") if s.strip()]
        if status_list:
            conditions.append(MediaItem.status.in_(status_list))

    # 2. Media Type (Exact Match, supports comma-separated)
    if media_type and media_type != "all":
        type_list = [t.strip() for t in media_type.split(",") if t.strip()]
        if type_list:
            conditions.append(MediaItem.media_type.in_(type_list))

    # 3. Language (Fuzzy Match)
    if language:
        lang_list = [l.strip() for l in language.split(",") if l.strip()]
        if lang_list:
            conditions.append(
                or_(*[MediaItem.language.ilike(f"%{l}%") for l in lang_list])
            )

    # 4. Platform (Fuzzy Match)
    if platform:
        plat_list = [p.strip() for p in platform.split(",") if p.strip()]
        if plat_list:
            conditions.append(
                or_(*[MediaItem.platform.ilike(f"%{p}%") for p in plat_list])
            )

    # 5. Genres (Universal Text Search)
    # Handles comma-separated values (e.g., "Action, Comedy")
    if genres:
        genres_list = [g.strip() for g in genres.split(",") if g.strip()]
        for genre in genres_list:
            # FIX: Cast to Text universally.
            # This works on both SQLite and Postgres and avoids JSON syntax errors.
            # We search for "Genre" (with quotes) to ensure we match the exact JSON string.
            conditions.append(cast(MediaItem.genres, Text).ilike(f'%"{genre}"%'))

    # 6. General Search (Title OR IDs)
    if q and q.strip():
        search_term = q.strip()
        conditions.append(
            or_(
                MediaItem.title.ilike(f"%{search_term}%"),
                MediaItem.imdb_id == search_term,
                cast(MediaItem.tmdb_id, String) == search_term,
            )
        )

    # Apply conditions
    for cond in conditions:
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    # Get Total Count
    total_res = await db.execute(count_stmt)
    total = total_res.scalar_one()

    # Get Paginated Items
    stmt = (
        stmt.offset(skip)
        .limit(limit)
        .order_by(
            MediaItem.streaming_date.desc().nulls_last(), MediaItem.created_at.desc()
        )
    )
    result = await db.execute(stmt)
    items = result.scalars().all()

    return items, total
