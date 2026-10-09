"""``GET /favicon.ico``: a neutral icon, so browsers asking for it do not get a 404."""

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.adapters.web.dependencies import STATIC_DIR

router = APIRouter()

FAVICON = STATIC_DIR / "favicon.ico"


@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(FAVICON, media_type="image/x-icon")
