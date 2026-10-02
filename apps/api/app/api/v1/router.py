from fastapi import APIRouter

from app.api.v1 import health
from app.quality.moisture import router as moisture

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(moisture.router)
