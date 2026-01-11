from typing import Any, Dict, Optional


class MediaManagerError(Exception):
    """Base class for all application-specific exceptions."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details
        super().__init__(self.message)


class ItemNotFoundError(MediaManagerError):
    """Raised when a requested resource is not found."""

    def __init__(self, item_id: Any, item_type: str = "Item"):
        super().__init__(
            message=f"{item_type} with ID '{item_id}' not found.",
            code="ITEM_NOT_FOUND",
            status_code=404,
        )


class ExternalApiError(MediaManagerError):
    """Raised when an external service (TMDB) fails."""

    def __init__(self, service_name: str, original_error: str):
        super().__init__(
            message=f"External service '{service_name}' failed: {original_error}",
            code="EXTERNAL_API_ERROR",
            status_code=502,
        )


class ScraperError(MediaManagerError):
    """Raised when scraping fails."""

    def __init__(self, reason: str):
        super().__init__(
            message=f"Scraping failed: {reason}", code="SCRAPER_ERROR", status_code=500
        )


class DatabaseError(MediaManagerError):
    """Raised for DB integrity or connection issues."""

    def __init__(self, detail: str):
        super().__init__(
            message=f"Database error: {detail}", code="DATABASE_ERROR", status_code=500
        )
