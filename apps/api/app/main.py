import logging

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    app = FastAPI(
        title="Operations Platform API",
        version=settings.app_version,
        docs_url="/api/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.docs_enabled else None,
    )
    app.include_router(api_router)
    return app


app = create_app()
