"""All v1 routers."""

from fastapi import APIRouter

from app.api.v1 import auth, analyses, telegram, training, dashboard

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(analyses.router)
api_router.include_router(telegram.router)
api_router.include_router(training.router)
api_router.include_router(dashboard.router)
# share is mounted at root path (not /api) for clean public URLs
