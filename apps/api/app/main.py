import logging
import os

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import get_settings

# Settings of the pre-sign-in development mode. Users, roles and permissions now
# live in the database; these are ignored.
RETIRED_SETTINGS = ("USER_AUTH_MODE", "DEVELOPMENT_USER_PERMISSIONS")


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    for name in RETIRED_SETTINGS:
        if name in os.environ:
            logging.getLogger(__name__).warning(
                "event=retired_setting name=%s; it is ignored, remove it from the environment",
                name,
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
