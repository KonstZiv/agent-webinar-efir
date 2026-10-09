"""``GET /healthz``: 200 only when the database answers (settings are checked at startup).

``HEAD`` is answered too: uptime monitors often probe with it. The redirect mode spares this
path (``HEALTH_PATH``), so the platform's health check keeps reaching the service.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.adapters.web.dependencies import ContainerDep
from app.adapters.web.headers import SERVICE

router = APIRouter()

HEALTH_PATH = "/healthz"


@router.api_route(HEALTH_PATH, methods=["GET", "HEAD"])
def healthz(container: ContainerDep) -> JSONResponse:
    if container.db_probe.is_available():
        return JSONResponse({"status": "ok"}, headers=SERVICE)
    return JSONResponse({"status": "unavailable"}, status_code=503, headers=SERVICE)
