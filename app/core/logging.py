import logging
import sys
import os
from logging.handlers import RotatingFileHandler

# Create data/logs directory if not exists
LOG_DIR = "data/logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "mediaflow.log")


def setup_logging():
    """Configures the root logger for the entire application."""

    # Get console log level from environment (default INFO)
    console_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    console_level = getattr(logging, console_level_str, logging.INFO)

    # Create a custom formatter
    log_format = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 1. Console Handler (Standard Output) - Configurable level
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(log_format)

    # 2. File Handler (Rotating) - DEBUG level (always captures everything)
    # Rotates after 5MB, keeps last 3 backup files
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(log_format)

    # Apply to Root Logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture everything

    # Avoid duplicate logs if function called twice
    if not root_logger.handlers:
        root_logger.addHandler(console_handler)
        root_logger.addHandler(file_handler)

    # Silence noisy libraries (optional)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)

    return root_logger
