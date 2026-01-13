import logging
import aiohttp
import asyncio
import re
import html
import random
import os
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class BingedScraper:
    BINGED_URL = "https://www.binged.com/wp-admin/admin-ajax.php"

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    ]

    PLATFORM_MAPPING = {
        "10": "Jio Hotstar",
        "4": "Prime Video",
        "52": "Zee5",
        "30": "Netflix",
        "39": "Sony Liv",
        "16": "Google Play",
        "5": "Apple Tv+",
        "2": "Aha",
        "21": "Jio Cinema",
        "6": "Book my Show",
        "26": "Lionsgate",
        "41": "Sun Nxt",
        "55": "Etv Win",
        "59": "Ultra Play",
    }

    GENRE_ALLOWLIST = [
        "Action",
        "Adventure",
        "Animation",
        "Biography",
        "Comedy",
        "Crime",
        "Drama",
        "Family",
        "Fantasy",
        "History",
        "Horror",
        "Kids",
        "Musical",
        "Mystery",
        "Political",
        "Romance",
        "Sci-Fi",
        "Sports",
        "Thriller",
        "War",
        "Western",
    ]

    PLATFORM_ALLOWLIST = [
        "Aha Video",
        "Amazon",
        "ETV Win",
        "Jio Hotstar",
        "Netflix",
        "Sony LIV",
        "Sun NXT",
        "Zee5",
        "Apple Tv Plus",
    ]

    GENRE_PARTIAL_BLOCKLIST = [
        "reality",
        "documentary",
        "talk",
        "news",
        "game",
        "stand-up",
        "shorts",
        "mini",
        "music",
    ]
    GENRE_EXACT_BLOCKLIST = ["music"]

    def __init__(self):
        self.headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Origin": "https://www.binged.com",
            "Referer": "https://www.binged.com/streaming-premiere-dates/",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": random.choice(self.USER_AGENTS),
        }
        # Concurrency Control: Allow 5 concurrent requests to Binged
        self.sem = asyncio.Semaphore(5)

    async def _fetch(
        self, session: aiohttp.ClientSession, url, method="GET", data=None, retries=3
    ):
        """
        Robust fetch with exponential backoff for retries using provided session.
        """
        for attempt in range(1, retries + 1):
            try:
                if method == "POST":
                    async with session.post(
                        url, headers=self.headers, data=data, timeout=15
                    ) as resp:
                        if resp.status == 200:
                            return await resp.json()
                        elif resp.status == 429:
                            logger.warning(
                                f"Rate limited (429) on {url}. Waiting 60s before retry ({attempt}/{retries})..."
                            )
                            await asyncio.sleep(60)
                        elif resp.status in [500, 502, 503, 504]:
                            logger.warning(
                                f"Server error {resp.status} on {url}. Retrying ({attempt}/{retries})..."
                            )
                        else:
                            logger.error(f"Failed {url} with status {resp.status}")
                            return None
                else:
                    async with session.get(
                        url, headers=self.headers, timeout=15
                    ) as resp:
                        if resp.status == 200:
                            if "wp-json" in url:
                                return await resp.json()
                            else:
                                return await resp.text()
                        elif resp.status == 429:
                            logger.warning(
                                f"Rate limited (429) on {url}. Waiting 60s before retry ({attempt}/{retries})..."
                            )
                            await asyncio.sleep(60)
                        elif resp.status in [500, 502, 503, 504]:
                            logger.warning(
                                f"Server error {resp.status} on {url}. Retrying ({attempt}/{retries})..."
                            )
                        else:
                            return None

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(
                    f"Network error on {url}: {e}. Retrying ({attempt}/{retries})..."
                )

            if attempt < retries:
                await asyncio.sleep(2**attempt)

        logger.error(f"Max retries reached for {url}")
        return None

    def _clean_title(self, title: str) -> str:
        if not title:
            return ""
        cleaned = html.unescape(title)
        cleaned = re.sub(r"\s?\(.*?\)", "", cleaned)
        cleaned = re.sub(r"(?i)\b(Season|S)\s*\d+.*", "", cleaned)
        return cleaned.strip()

    async def _fetch_details_concurrently(
        self, session: aiohttp.ClientSession, item: Dict
    ) -> Optional[str]:
        """
        Helper task to fetch IMDB details.
        Uses semaphore to limit concurrency and preserves original logging.
        """
        async with self.sem:
            binged_imdb_id = None
            item_id = item.get("id")
            title = item.get("title", "Unknown")

            if item_id:
                logger.debug(f"Fetching IMDB for item ID {item_id}")
                # Sleep removed to improve speed (concurrency limits rate instead)

                api_url = (
                    f"https://www.binged.com/wp-json/binged-api/v1/movie/{item_id}"
                )
                detail_data = await self._fetch(session, api_url)
                if detail_data and "imdb" in detail_data:
                    imdb_value = detail_data["imdb"]
                    if imdb_value and imdb_value.strip():
                        binged_imdb_id = imdb_value.strip()
                        logger.debug(f"Found IMDB ID: {binged_imdb_id}")
                    else:
                        logger.debug("No IMDB ID found in API response")
                else:
                    logger.warning(f"Failed to fetch API data for item {item_id}")
            else:
                logger.warning(f"No item ID found for {title}")

            return binged_imdb_id

    async def scrape_page(
        self, session: aiohttp.ClientSession, page_number: int, category: str = "movie"
    ) -> List[Dict]:
        """
        Scrapes a SINGLE page (50 items) defined by page_number (0-indexed).
        Uses the provided session for better performance.
        """
        logger.debug(f"Starting scrape for page {page_number}, category: {category}")
        results = []
        binged_category = "Film" if category == "movie" else "Tv show"
        logger.debug(f"Using Binged category: {binged_category}")

        start_offset = page_number * 50

        logger.debug(
            f"Scraping Page {page_number + 1} (Offset {start_offset}) | Cat: {category}"
        )

        payload = {
            "action": "mi_events_load_data",
            "filters[category][]": binged_category,
            "filters[mode]": "streaming-now",
            "filters[genre][]": self.GENRE_ALLOWLIST,
            "filters[platform][]": self.PLATFORM_ALLOWLIST,
            "start": start_offset,
            "length": 50,
        }
        logger.debug(f"AJAX payload: {payload}")

        data = await self._fetch(session, self.BINGED_URL, "POST", payload)
        if not data or "data" not in data:
            logger.warning(f"No data returned for page {page_number}")
            return []

        logger.debug(f"Received {len(data['data'])} items from AJAX")

        # 1. Prepare items and tasks
        valid_items = []
        tasks = []

        for item in data["data"]:
            # GENRE FILTERING
            genres_str = item.get("genre", "")
            if genres_str:
                genres_lower = genres_str.lower()
                if any(bad in genres_lower for bad in self.GENRE_PARTIAL_BLOCKLIST):
                    continue
                if any(
                    g.strip() in self.GENRE_EXACT_BLOCKLIST
                    for g in genres_lower.split(",")
                ):
                    continue

            # Basic Info
            title = item.get("title", "Unknown")
            logger.debug(f"Processing item: {title}")

            valid_items.append(item)
            tasks.append(self._fetch_details_concurrently(session, item))

        # 2. Execute tasks concurrently
        # This replaces the sequential sleep/fetch loop
        imdb_ids = await asyncio.gather(*tasks)

        # 3. Assemble Results
        for item, binged_imdb_id in zip(valid_items, imdb_ids):
            title = item.get("title", "Unknown")
            raw_url = item.get("link", "")

            # EXTRACT LANGUAGES
            languages = item.get("languages", "")

            # Platform
            platform_ids = item.get("platform", [])
            platform_name = "Other"
            if isinstance(platform_ids, list):
                for url in platform_ids:
                    match = re.search(r"/(\d+)\.webp", url)
                    if match and match.group(1) in self.PLATFORM_MAPPING:
                        platform_name = self.PLATFORM_MAPPING[match.group(1)]
                        break

            # Extract Date
            raw_date = (
                item.get("streaming-date")
                or item.get("release-date")
                or item.get("date")
            )
            streaming_date = None
            if raw_date and isinstance(raw_date, str):
                date_formats = ["%d %b %Y", "%Y-%m-%d"]
                for fmt in date_formats:
                    try:
                        streaming_date = datetime.strptime(raw_date.strip(), fmt).date()
                        break
                    except (ValueError, TypeError):
                        continue

            results.append(
                {
                    "title": self._clean_title(title),
                    "year": item.get("release-year", 0),
                    "binged_url": raw_url,
                    "binged_imdb_id": binged_imdb_id,
                    "platform": platform_name,
                    "streaming_date": streaming_date,
                    "languages": languages,
                    "raw_data": item,
                }
            )

        return results
