import logging
import re
import json
from sqlalchemy.future import select
from sqlalchemy import func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import ScrapedItem, MediaItem, MediaType, MediaStatus, ScrapeStatus
from app.scrapers.binged import BingedScraper
from app.services.metadata import MetadataService
from app.core.config import settings

logger = logging.getLogger(__name__)


class IngestionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.scraper = BingedScraper()
        self.metadata = MetadataService()

    def _parse_safe_year(self, year_val) -> int:
        """Robustly extracts a year from potentially messy Binged data."""
        if not year_val:
            return 0
        if isinstance(year_val, int):
            return year_val
        try:
            match = re.search(r"(\d{4})", str(year_val))
            if match:
                return int(match.group(1))
            return int(year_val)
        except (ValueError, TypeError):
            return 0

    async def _get_db_count(self, model, media_type: MediaType = None) -> int:
        """Generic count helper."""
        stmt = select(func.count(model.id))

        # Filter by media_type if provided and model supports it
        if media_type and hasattr(model, "media_type"):
            stmt = stmt.where(model.media_type == media_type.value)

        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def run_daily_scan(self):
        """
        Orchestrates the ingestion process:
        1. Scrape raw data -> ScrapedItems
        2. Process pending items -> MediaItems
        """
        logger.info("Starting Daily Ingestion...")
        logger.debug("Initializing scraper and metadata services")

        # 1. Scrape Phase (Fill Buffer)
        await self._scrape_phase(MediaType.MOVIE)
        await self._scrape_phase(MediaType.SERIES)

        # 2. Processing Phase (Promote All)
        await self.process_scraped_items()

        logger.info("Ingestion Cycle Completed.")

    async def _scrape_phase(self, media_type: MediaType):
        """Runs the scraper and fills ScrapedItems table."""
        logger.debug(f"Starting scrape phase for {media_type.value}")
        # Pass media_type to get correct count for maintenance logic
        count = await self._get_db_count(ScrapedItem, media_type)
        logger.debug(f"Current {media_type.value} count in database: {count}")

        if count < 100:
            mode = "BACKFILL"
            max_pages = settings.MAX_PAGES_BACKFILL
        else:
            mode = "MAINTENANCE"
            max_pages = settings.MAX_PAGES_MAINTENANCE

        logger.info(
            f"Scraping {media_type.value} in {mode} mode ({max_pages} pages). Current DB Count: {count}"
        )

        category_str = "movie" if media_type == MediaType.MOVIE else "series"
        logger.debug(f"Using category string: {category_str}")

        for page_num in range(max_pages):
            logger.debug(
                f"Scraping page {page_num + 1}/{max_pages} for {media_type.value}"
            )
            items = await self.scraper.scrape_page(page_num, category_str)
            if not items:
                logger.warning(
                    f"No items found on page {page_num + 1}, stopping scrape"
                )
                break

            activity = await self._save_raw_batch(items, media_type)
            logger.debug(f"Page {page_num + 1}: saved {activity} new/updated items")

            if mode == "MAINTENANCE" and activity == 0:
                logger.info(
                    "No new/updated raw items found. Stopping maintenance scrape."
                )
                break

    async def _save_raw_batch(self, items: list, media_type: MediaType) -> int:
        """Upserts raw items into ScrapedItem table. Returns count of changes."""
        if not items:
            logger.debug("No items to save in batch")
            return 0

        logger.debug(f"Saving batch of {len(items)} items for {media_type.value}")
        activity_count = 0

        # 1. Bulk Fetch
        source_urls = [item["binged_url"] for item in items]
        stmt = select(ScrapedItem).where(ScrapedItem.source_url.in_(source_urls))
        result = await self.db.execute(stmt)

        existing_items_map = {item.source_url: item for item in result.scalars().all()}
        logger.debug(f"Found {len(existing_items_map)} existing items in database")

        for item_data in items:
            source_url = item_data["binged_url"]
            existing = existing_items_map.get(source_url)
            title = item_data.get("title", "Unknown")

            # PREPARE RAW DATA
            raw_blob = item_data["raw_data"]
            raw_blob["inferred_type"] = media_type.value
            if item_data.get("binged_imdb_id"):
                raw_blob["binged_imdb_id"] = item_data["binged_imdb_id"]

            if existing:
                existing.raw_data = raw_blob
                existing.scrape_status = ScrapeStatus.PENDING
                logger.info(f"Updated Raw Item: {title}")
                activity_count += 1
            else:
                new_scraped = ScrapedItem(
                    source_url=source_url,
                    title=title,
                    year=self._parse_safe_year(item_data.get("year")),
                    media_type=media_type.value,  # Explicitly save media_type
                    platform=item_data["platform"],
                    raw_data=raw_blob,
                    scrape_status=ScrapeStatus.PENDING,
                )
                self.db.add(new_scraped)
                logger.info(f"New Raw Item Scraped: {title}")
                activity_count += 1

        await self.db.commit()
        logger.debug(f"Committed {activity_count} changes to database")
        return activity_count

    async def process_scraped_items(self):
        """
        Reads PENDING items from ScrapedItem in batches and promotes them to MediaItem.
        Uses Batch Caching to prevent IntegrityErrors and Smart Date Logic for updates.
        """
        logger.info("Processing PENDING scraped items (Batch Size: 50)...")
        batch_size = 50
        total_processed = 0

        while True:
            # Fetch a batch of pending items
            stmt = (
                select(ScrapedItem)
                .where(ScrapedItem.scrape_status == ScrapeStatus.PENDING)
                .limit(batch_size)
            )

            result = await self.db.execute(stmt)
            pending_items = result.scalars().all()

            if not pending_items:
                break

            logger.info(f"Processing batch of {len(pending_items)} items...")

            # --- Batch Cache ---
            # Used to track items created/loaded in THIS batch to prevent duplicates
            batch_tmdb_map = {}
            batch_imdb_map = {}
            batch_url_map = {}

            for scraped in pending_items:
                try:
                    # 1. Extract Data
                    raw = scraped.raw_data

                    # Prefer the explicit column, fallback to JSON for legacy
                    media_type_str = scraped.media_type or raw.get(
                        "inferred_type", "movie"
                    )
                    try:
                        media_type = MediaType(media_type_str)
                    except ValueError:
                        media_type = MediaType.MOVIE

                    languages = raw.get("languages", "")

                    # 2. Metadata Matching
                    binged_imdb = raw.get("binged_imdb_id")
                    title = scraped.title
                    year = scraped.year

                    match_data = None
                    if binged_imdb:
                        match_data = await self.metadata.get_details_by_imdb(
                            binged_imdb, media_type
                        )

                    if not match_data:
                        match_data = await self.metadata.search_by_query(
                            title, year, media_type
                        )

                    if not match_data:
                        logger.warning(f"No Metadata Match found for: {title} ({year})")

                    # 3. Upsert MediaItem
                    existing_media = None

                    # A. Check Batch Cache First
                    if match_data:
                        if (
                            match_data.get("tmdb_id")
                            and match_data["tmdb_id"] in batch_tmdb_map
                        ):
                            existing_media = batch_tmdb_map[match_data["tmdb_id"]]
                        elif (
                            match_data.get("imdb_id")
                            and match_data["imdb_id"] in batch_imdb_map
                        ):
                            existing_media = batch_imdb_map[match_data["imdb_id"]]

                    if not existing_media and scraped.source_url in batch_url_map:
                        existing_media = batch_url_map[scraped.source_url]

                    # B. Check Database if not in cache
                    if not existing_media:
                        if match_data:
                            conds = []
                            if match_data.get("tmdb_id"):
                                conds.append(MediaItem.tmdb_id == match_data["tmdb_id"])
                            if match_data.get("imdb_id"):
                                conds.append(MediaItem.imdb_id == match_data["imdb_id"])

                            if conds:
                                media_stmt = select(MediaItem).where(or_(*conds))
                                media_res = await self.db.execute(media_stmt)
                                existing_media = media_res.scalars().first()

                        if not existing_media:
                            url_stmt = select(MediaItem).where(
                                MediaItem.binged_url == scraped.source_url
                            )
                            url_res = await self.db.execute(url_stmt)
                            existing_media = url_res.scalars().first()

                        # Add found DB item to Cache
                        if existing_media:
                            if existing_media.tmdb_id:
                                batch_tmdb_map[existing_media.tmdb_id] = existing_media
                            if existing_media.imdb_id:
                                batch_imdb_map[existing_media.imdb_id] = existing_media
                            if existing_media.binged_url:
                                batch_url_map[existing_media.binged_url] = (
                                    existing_media
                                )

                    if existing_media:
                        # UPDATE existing - Smart Date Logic

                        # 1. Always update metadata if available (IDs, Poster, Overview)
                        if match_data:
                            existing_media.tmdb_id = (
                                match_data.get("tmdb_id") or existing_media.tmdb_id
                            )
                            existing_media.imdb_id = (
                                match_data.get("imdb_id") or existing_media.imdb_id
                            )
                            existing_media.overview = (
                                match_data.get("overview") or existing_media.overview
                            )
                            existing_media.poster_url = (
                                match_data.get("poster_url")
                                or existing_media.poster_url
                            )
                            existing_media.backdrop_url = (
                                match_data.get("backdrop_url")
                                or existing_media.backdrop_url
                            )

                        if languages:
                            existing_media.language = languages

                        # 2. Update Source Info ONLY if newer
                        existing_media.platform = scraped.platform
                        existing_media.binged_url = scraped.source_url
                        existing_media.status = MediaStatus.APPROVED
                        logger.info(f"Updated MediaItem Source: {existing_media.title}")

                    else:
                        # CREATE new
                        new_media = MediaItem(
                            title=match_data.get("title") if match_data else title,
                            year=match_data.get("year") if match_data else year,
                            media_type=media_type.value,
                            language=languages,
                            tmdb_id=match_data.get("tmdb_id") if match_data else None,
                            imdb_id=match_data.get("imdb_id") if match_data else None,
                            overview=match_data.get("overview") if match_data else None,
                            poster_url=(
                                match_data.get("poster_url") if match_data else None
                            ),
                            backdrop_url=(
                                match_data.get("backdrop_url") if match_data else None
                            ),
                            genres=match_data.get("genres", []) if match_data else [],
                            binged_url=scraped.source_url,
                            platform=scraped.platform,
                            status=(
                                MediaStatus.APPROVED if match_data else MediaStatus.NEW
                            ),
                        )
                        self.db.add(new_media)
                        logger.info(f"Promoted New MediaItem: {new_media.title}")

                        # Add new item to Cache immediately
                        if new_media.tmdb_id:
                            batch_tmdb_map[new_media.tmdb_id] = new_media
                        if new_media.imdb_id:
                            batch_imdb_map[new_media.imdb_id] = new_media
                        if new_media.binged_url:
                            batch_url_map[new_media.binged_url] = new_media

                    # 4. Mark ScrapedItem as Complete
                    scraped.scrape_status = ScrapeStatus.PROCESSED

                except Exception as e:
                    logger.error(f"Error processing scraped item {scraped.id}: {e}")
                    scraped.scrape_status = ScrapeStatus.ERROR
                    scraped.error_message = str(e)

            # Commit after the batch
            await self.db.commit()
            total_processed += len(pending_items)
            logger.info(f"Batch committed. Total processed: {total_processed}")

        if total_processed == 0:
            logger.info("No pending items to process.")
        else:
            logger.info(
                f"Processing complete. Total items processed: {total_processed}"
            )
