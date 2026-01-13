import logging
import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.api import endpoints, stremio
from app.web import dashboard
from app.core.logging import setup_logging
from app.core.config import settings
from app.core.exceptions import MediaManagerError
from app.db.database import init_db, AsyncSessionLocal
from app.services.ingestion import IngestionService

# Setup global logging
setup_logging()
logger = logging.getLogger(__name__)

# Initialize Global Scheduler
scheduler = AsyncIOScheduler()


async def run_scheduled_ingestion():
    """Background task to run the daily scan."""
    logger.info("Background Task: Starting scheduled metadata ingestion...")
    logger.debug("Initializing database session for ingestion service")
    async with AsyncSessionLocal() as db:
        try:
            service = IngestionService(db)
            await service.run_daily_scan()
            logger.info("Background Task: Scheduled ingestion completed successfully.")
        except Exception as e:
            logger.error(f"Background Task Error: Ingestion failed: {e}", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles startup and shutdown events for the application.
    Replaces deprecated @app.on_event patterns.
    """
    # --- Startup Logic ---
    logger.info("MediaFlow API Starting up (Lifespan)...")
    logger.debug("Beginning application initialization sequence")

    # 1. Initialize Database Tables
    logger.debug("Initializing database tables...")
    await init_db()
    logger.info("Database tables initialized successfully")

    # 2. Configure & Start Ingestion Scheduler
    interval = settings.INGESTION_INTERVAL_HOURS
    logger.debug(f"Configuring ingestion scheduler with {interval} hour interval")
    scheduler.add_job(
        run_scheduled_ingestion,
        "interval",
        hours=interval,
        id="daily_ingestion",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Ingestion Scheduler active: every {interval} hours.")

    # 3. Trigger immediate scan in background so server isn't blocked
    logger.debug("Triggering initial background ingestion task")
    asyncio.create_task(run_scheduled_ingestion())

    yield  # --- Server is now running and handling requests ---

    # --- Shutdown Logic ---
    logger.info("MediaFlow API Shutting down (Lifespan)...")
    logger.debug("Shutting down scheduler...")
    scheduler.shutdown()
    logger.info("Scheduler shutdown complete")


# Initialize FastAPI with the lifespan context manager
app = FastAPI(title="MediaFlow API", version="1.0.0", lifespan=lifespan)

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure Static Directory exists and mount it
os.makedirs("app/static", exist_ok=True)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# --- Global Exception Handlers ---


@app.exception_handler(MediaManagerError)
async def media_manager_exception_handler(request: Request, exc: MediaManagerError):
    """Handles our custom application exceptions."""
    logger.warning(f"MediaManagerError handled: {exc.code} - {exc.message}")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {"code": exc.code, "message": exc.message, "details": exc.details}
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handles all unhandled exceptions to prevent server crashes and expose standard JSON."""
    logger.error(f"Unhandled Exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred. Please check the logs.",
                "details": str(exc),  # Consider hiding this in production
            }
        },
    )


# Register Routers
app.include_router(endpoints.router, prefix="/api")
app.include_router(stremio.router, prefix="/stremio")  # New Stremio Addon Router
app.include_router(dashboard.router)  # Legacy HTMX dashboard


@app.get("/")
async def root():
    logger.debug("Root endpoint accessed")
    return {"message": "MediaFlow API is running. Go to /dashboard"}


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting MediaFlow API with uvicorn...")
    # Start the application
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload_excludes=["data/*"],
    )
