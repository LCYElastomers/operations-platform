from fastapi import APIRouter

from app.api.v1 import health
from app.quality.moisture import ingestion_router as moisture_ingestion
from app.quality.moisture import router as moisture
from app.safety import router as safety
from app.safety.contacts import router as safety_contacts
from app.safety.observations import router as safety_observations
from app.safety.performance import router as safety_performance

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(moisture.router)
api_router.include_router(moisture_ingestion.router)
api_router.include_router(safety.router)
api_router.include_router(safety_observations.router)
api_router.include_router(safety_contacts.router)
api_router.include_router(safety_performance.router)
