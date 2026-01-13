import logging
import aiohttp
import asyncio
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager
from app.core.config import settings
from app.db.models import MediaType

logger = logging.getLogger(__name__)


class MetadataService:
    def __init__(self, session: Optional[aiohttp.ClientSession] = None):
        if not settings.TMDB_API_KEY:
            logger.warning("TMDB_API_KEY is missing! Metadata enrichment will fail.")

        self.headers = {
            "Authorization": f"Bearer {settings.TMDB_API_KEY}",
            "Content-Type": "application/json;charset=utf-8",
        }
        self.external_session = session
        self.delay = 0.2
        self.cinemeta_url = "https://v3-cinemeta.strem.io/meta"

    @asynccontextmanager
    async def _get_session(self):
        """
        Context manager to yield a session.
        Uses the external persistent session if available,
        otherwise creates a temporary one for the scope of the block.
        """
        if self.external_session and not self.external_session.closed:
            yield self.external_session
        else:
            async with aiohttp.ClientSession() as session:
                yield session

    # --- NEW HELPER METHOD ---
    def normalize_binged_data(self, raw_data: Dict) -> Dict:
        """
        Converts raw Binged JSON into a standard metadata format.
        Used as a fallback when TMDB/Cinemeta fails.
        """
        logger.info(f"Normalizing Binged data for: {raw_data.get('title')}")

        # 1. Parse Year
        year = 0
        try:
            if raw_data.get("release_year"):
                year = int(raw_data["release_year"])
        except (ValueError, TypeError):
            pass

        # 2. Parse Genres
        genres = []
        if isinstance(raw_data.get("genre"), list):
            genres = [g.replace("&amp;", "&").strip() for g in raw_data["genre"]]

        return {
            "tmdb_id": None,  # Binged does not provide TMDB IDs
            "imdb_id": raw_data.get("imdb", "").strip() or None,
            # CHANGED: Prefer 'title' (from listing/DB) over 'post_title'
            "title": raw_data.get("title") or raw_data.get("post_title"),
            "year": year,
            "overview": raw_data.get("post_content", ""),  # The description!
            "poster_url": raw_data.get("image"),  # The high-res image!
            "backdrop_url": None,
            "genres": genres,
            "source": "binged_fallback",
        }

    async def _fetch(
        self,
        session: aiohttp.ClientSession,
        endpoint: str,
        params: Dict = None,
        retries: int = 3,
    ) -> Optional[Dict]:
        """Robust TMDB fetcher."""
        url = f"{settings.TMDB_BASE_URL}{endpoint}"
        full_params = {"api_key": settings.TMDB_API_KEY}
        if params:
            full_params.update(params)

        logger.debug(f"Fetching TMDB endpoint: {endpoint} with params: {params}")
        for attempt in range(1, retries + 1):
            try:
                await asyncio.sleep(self.delay)
                async with session.get(url, params=full_params, timeout=10) as resp:
                    if resp.status == 200:
                        logger.debug(
                            f"Successfully fetched TMDB data for endpoint: {endpoint}"
                        )
                        return await resp.json()
                    elif resp.status == 429:
                        retry_after = int(resp.headers.get("Retry-After", 5))
                        logger.warning(
                            f"TMDB rate limit hit for endpoint {endpoint}, retrying after {retry_after}s"
                        )
                        await asyncio.sleep(retry_after)
                        continue
                    elif resp.status == 404:
                        logger.debug(
                            f"TMDB endpoint {endpoint} returned 404 (not found)"
                        )
                        return None
                    else:
                        logger.warning(
                            f"TMDB endpoint {endpoint} returned status {resp.status}"
                        )
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(
                    f"TMDB Network Error for endpoint {endpoint}: {e}. Attempt {attempt}/{retries}"
                )

            if attempt < retries:
                await asyncio.sleep(2**attempt)
        logger.error(
            f"Failed to fetch TMDB data for endpoint {endpoint} after {retries} attempts"
        )
        return None

    async def _fetch_cinemeta(
        self, imdb_id: str, media_type: MediaType
    ) -> Optional[Dict[str, Any]]:
        """Fallback to Cinemeta (Stremio) if TMDB fails."""
        c_type = "movie" if media_type == MediaType.MOVIE else "series"
        url = f"{self.cinemeta_url}/{c_type}/{imdb_id}.json"

        logger.debug(f"Fetching Cinemeta data for IMDB ID: {imdb_id}, type: {c_type}")
        async with self._get_session() as session:
            try:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        meta = data.get("meta")
                        if not meta:
                            logger.debug(
                                f"No meta data found in Cinemeta response for {imdb_id}"
                            )
                            return None

                        # Extract year safely from releaseInfo (usually "YYYY")
                        year_str = str(meta.get("releaseInfo", ""))
                        year = (
                            int(year_str[:4])
                            if year_str and year_str[:4].isdigit()
                            else 0
                        )

                        logger.info(
                            f"Successfully fetched Cinemeta data for {imdb_id}: {meta.get('name')}"
                        )
                        return {
                            "tmdb_id": None,  # Cinemeta doesn't always provide this
                            "imdb_id": imdb_id,
                            "title": meta.get("name"),
                            "year": year,
                            "overview": meta.get("description"),
                            "poster_url": meta.get("poster"),
                            "backdrop_url": meta.get("background"),
                            "genres": meta.get("genres", []),
                            "source": "cinemeta",
                        }
            except Exception as e:
                logger.error(f"Cinemeta Error for {imdb_id}: {e}")
        return None

    async def get_details_by_tmdb_id(
        self, tmdb_id: int, media_type: MediaType
    ) -> Optional[Dict[str, Any]]:
        logger.debug(f"Getting details by TMDB ID: {tmdb_id}, type: {media_type.value}")
        async with self._get_session() as session:
            result = await self._format_result(session, {"id": tmdb_id}, media_type)
            if result:
                logger.info(
                    f"Successfully retrieved details for TMDB ID {tmdb_id}: {result.get('title')}"
                )
            else:
                logger.warning(f"No details found for TMDB ID: {tmdb_id}")
            return result

    async def get_details_by_imdb(
        self, imdb_id: str, media_type: Optional[MediaType] = None
    ) -> Optional[Dict[str, Any]]:
        """Try TMDB first, fallback to Cinemeta."""
        logger.debug(
            f"Getting details by IMDB ID: {imdb_id}, type: {media_type.value if media_type else None}"
        )
        async with self._get_session() as session:
            data = await self._fetch(
                session, f"/find/{imdb_id}", {"external_source": "imdb_id"}
            )

            result = None
            resolved_type = media_type

            if data:
                if data.get("movie_results"):
                    result = data["movie_results"][0]
                    resolved_type = MediaType.MOVIE
                    logger.debug(f"Found movie result for IMDB ID {imdb_id}")
                elif data.get("tv_results"):
                    result = data["tv_results"][0]
                    resolved_type = MediaType.SERIES
                    logger.debug(f"Found series result for IMDB ID {imdb_id}")

            if result:
                formatted_result = await self._format_result(
                    session, result, resolved_type
                )
                if formatted_result:
                    logger.info(
                        f"Successfully retrieved TMDB details for IMDB ID {imdb_id}: {formatted_result.get('title')}"
                    )
                    return formatted_result

            # Fallback to Cinemeta
            if resolved_type:
                logger.info(f"TMDB missed {imdb_id}. Falling back to Cinemeta...")
                cinemeta_result = await self._fetch_cinemeta(imdb_id, resolved_type)
                if cinemeta_result:
                    logger.info(
                        f"Successfully retrieved Cinemeta details for IMDB ID {imdb_id}: {cinemeta_result.get('title')}"
                    )
                return cinemeta_result

            logger.warning(f"No metadata found for IMDB ID: {imdb_id}")
            return None

    async def search_by_query(
        self, title: str, year: int, media_type: MediaType
    ) -> Optional[Dict[str, Any]]:
        endpoint = "/search/movie" if media_type == MediaType.MOVIE else "/search/tv"
        logger.debug(
            f"Searching TMDB by query: '{title}' ({year}), type: {media_type.value}"
        )
        async with self._get_session() as session:
            params = {"query": title}
            if media_type == MediaType.MOVIE and year:
                params["primary_release_year"] = year

            data = await self._fetch(session, endpoint, params)

            if (not data or not data.get("results")) and media_type == MediaType.SERIES:
                params.pop("primary_release_year", None)
                data = await self._fetch(session, endpoint, params)

            if not data or not data.get("results"):
                logger.debug(f"No search results found for '{title}' ({year})")
                return None

            candidates = data["results"]
            logger.debug(f"Found {len(candidates)} search candidates for '{title}'")
            best_match = None
            for candidate in candidates:
                if self._validate_match(candidate, year, media_type):
                    best_match = candidate
                    break

            if best_match:
                formatted_result = await self._format_result(
                    session, best_match, media_type
                )
                if formatted_result:
                    logger.info(
                        f"Found best match for '{title}': {formatted_result.get('title')} ({formatted_result.get('year')})"
                    )
                return formatted_result
            logger.debug(f"No valid match found for '{title}' ({year})")
            return None

    def _validate_match(
        self, item: Dict, target_year: int, media_type: MediaType
    ) -> bool:
        if not target_year:
            return True
        date_str = item.get("release_date") or item.get("first_air_date") or ""
        if not date_str:
            return False
        year = int(date_str[:4])
        if media_type == MediaType.MOVIE:
            return abs(year - target_year) <= 1
        return year <= target_year

    async def _format_result(
        self, session: aiohttp.ClientSession, item: Dict, media_type: MediaType
    ) -> Dict:
        tmdb_id = item.get("id")
        logger.debug(
            f"Formatting result for TMDB ID: {tmdb_id}, type: {media_type.value}"
        )
        details_endpoint = (
            f"/movie/{tmdb_id}" if media_type == MediaType.MOVIE else f"/tv/{tmdb_id}"
        )
        details = await self._fetch(
            session, details_endpoint, {"append_to_response": "external_ids"}
        )
        source = details if details else item

        imdb_id = None
        if details and "external_ids" in details:
            imdb_id = details["external_ids"].get("imdb_id")
        elif details:
            imdb_id = details.get("imdb_id")

        title = source.get("title") or source.get("name")
        date_str = source.get("release_date") or source.get("first_air_date")
        year = int(date_str[:4]) if date_str and len(date_str) >= 4 else 0

        result = {
            "tmdb_id": tmdb_id,
            "imdb_id": imdb_id,
            "title": title,
            "year": year,
            "overview": source.get("overview"),
            "poster_url": (
                f"https://image.tmdb.org/t/p/w500{source.get('poster_path')}"
                if source.get("poster_path")
                else None
            ),
            "backdrop_url": (
                f"https://image.tmdb.org/t/p/w1280{source.get('backdrop_path')}"
                if source.get("backdrop_path")
                else None
            ),
            "genres": [g["name"] for g in details.get("genres", [])] if details else [],
            "source": "tmdb",
        }
        logger.debug(f"Formatted metadata result: {title} ({year})")
        return result
