from fastapi import APIRouter

from app.api.v1 import health
from app.quality.cost import router as quality_cost
from app.quality.moisture import ingestion_router as moisture_ingestion
from app.quality.moisture import router as moisture
from app.safety import router as safety
from app.safety.observations import router as safety_observations
from app.safety.performance import router as safety_performance
from app.safety.records import router as safety_records
from app.safety.trir import router as safety_trir

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(moisture.router)
api_router.include_router(moisture_ingestion.router)
api_router.include_router(quality_cost.router)
api_router.include_router(safety.router)
api_router.include_router(safety_records.router)
api_router.include_router(safety_observations.router)
api_router.include_router(safety_performance.router)
api_router.include_router(safety_trir.router)
