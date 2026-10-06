from fastapi import APIRouter

from app.api.v1 import health
from app.quality.moisture import ingestion_router as moisture_ingestion
from app.quality.moisture import router as moisture
from app.safety import router as safety

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(moisture.router)
api_router.include_router(moisture_ingestion.router)
api_router.include_router(safety.router)
