import os
from typing import List, Optional, Union, Any
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    PROJECT_NAME: str = "MediaFlow Manager"
    API_V1_STR: str = "/api/v1"

    # Database
    DATABASE_URL: str

    # External APIs
    TMDB_API_KEY: str
    TMDB_BASE_URL: str = "https://api.themoviedb.org/3"

    # Scraper Config
    # Updated type hints to Union[List[str], str] to prevent Pydantic from forcing JSON parsing on env vars
    MOVIES_TARGET_LANGUAGES: Union[List[str], str] = [
        "Hindi",
        "Telugu",
        "Tamil",
        "Malayalam",
        "Kannada",
    ]
    SERIES_TARGET_LANGUAGES: Union[List[str], str] = [
        "Hindi",
        "Telugu",
        "Tamil",
        "Malayalam",
        "Kannada",
    ]
    SCRAPER_PAGES_MAINTENANCE: int = 1
    SCRAPER_PAGES_BACKFILL: int = 5
    INGESTION_INTERVAL_HOURS: int = 6
    MAX_PAGES_BACKFILL: int = 5
    MAX_PAGES_MAINTENANCE: int = 1

    # New Pydantic V2 Configuration for .env
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore"
    )

    @field_validator(
        "MOVIES_TARGET_LANGUAGES",
        "SERIES_TARGET_LANGUAGES",
        mode="before",
    )
    @classmethod
    def split_comma_separated_string(cls, v: Any) -> List[str]:
        if isinstance(v, str):
            if not v.strip():
                return []
            return [i.strip() for i in v.split(",") if i.strip()]
        if isinstance(v, list):
            return v
        return []


settings = Settings()
