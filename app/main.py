"""FastAPI entry point — single-user Gold Nightmare Personal."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.utils.logger import setup_logging

setup_logging()
logger = logging.getLogger("gn_personal")

# Templates & static
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "frontend" / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown."""
    logger.info("Starting %s v%s [%s]", settings.APP_NAME, settings.APP_VERSION, settings.APP_ENV)

    # Create tables (skip if Alembic is in charge)
    if "sqlite" in settings.DATABASE_URL.lower():
        from app.db.base import init_db
        await init_db()

    # Sentry
    if settings.SENTRY_DSN:
        try:
            import sentry_sdk
            sentry_sdk.init(dsn=settings.SENTRY_DSN, traces_sample_rate=0.1, environment=settings.APP_ENV)
            logger.info("Sentry initialized")
        except ImportError:
            logger.info("Sentry SDK not installed; skipping")

    # Background scheduler (training jobs)
    scheduler = None
    if settings.ENABLE_BACKGROUND_SCHEDULER:
        try:
            from app.training.scheduler import get_scheduler
            scheduler = get_scheduler()
            scheduler.start()
        except Exception as e:
            logger.warning("Could not start scheduler: %s", e)

    yield

    logger.info("Shutting down...")
    if scheduler is not None:
        try:
            scheduler.stop()
        except Exception:
            pass

    from app.db.base import engine
    await engine.dispose()


# ─── App ───

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url="/api/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Exception handlers ───

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": "خطأ في البيانات المرسلة", "errors": exc.errors(), "status": 422},
    )


# ─── Static + API routers ───

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "frontend" / "static")), name="static")

from app.api.v1 import api_router
from app.api.v1 import share
app.include_router(api_router, prefix="/api/v1")
app.include_router(share.router)  # public, mounted at root


# ─── HTML pages ───

@app.get("/health", include_in_schema=False)
async def health():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "env": settings.APP_ENV,
        "model": settings.CLAUDE_MODEL,
    }


@app.get("/api/info", include_in_schema=False)
async def app_info():
    """Public app info — used by login page."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "owner_name": settings.OWNER_DISPLAY_NAME,
        "max_upload_mb": settings.MAX_UPLOAD_MB,
        "max_images_per_analysis": settings.MAX_IMAGES_PER_ANALYSIS,
        "telegram_bot_username": settings.TELEGRAM_BOT_USERNAME,
        "features": {
            "share_links": settings.ENABLE_SHARE_LINKS,
            "pdf_export": settings.ENABLE_PDF_EXPORT,
            "few_shot": settings.ENABLE_FEW_SHOT_LEARNING,
            "ml_classifier": settings.ENABLE_ML_CLASSIFIER,
        },
    }


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "settings": settings})


@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "settings": settings})


@app.get("/history", response_class=HTMLResponse, include_in_schema=False)
async def history_page(request: Request):
    return templates.TemplateResponse("history.html", {"request": request, "settings": settings})


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_page(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request, "settings": settings})


@app.get("/training", response_class=HTMLResponse, include_in_schema=False)
async def training_page(request: Request):
    return templates.TemplateResponse("training.html", {"request": request, "settings": settings})


@app.get("/share/{token}", response_class=HTMLResponse, include_in_schema=False)
async def share_view(request: Request, token: str):
    return templates.TemplateResponse(
        "share.html", {"request": request, "settings": settings, "token": token},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app", host=settings.HOST, port=settings.PORT,
        reload=settings.DEBUG, log_level=settings.LOG_LEVEL.lower(),
    )
