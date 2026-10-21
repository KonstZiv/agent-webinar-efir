"""``GET /admin/stats`` and ``GET /admin/export.csv`` (docs/requirements.md, section 8).

Behind the admin token (``AdminDep``, checked before anything is built); never cached or
indexed. A database failure of any kind is 503 ``{"status": "unavailable"}``, as v1 answers.
The export holds personal data: the log gets the number of rows only.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response

from app.adapters.extras.csv_file import to_csv
from app.adapters.extras.keys import REPORTS, STATISTICS
from app.adapters.web.admin_auth import AdminDep
from app.adapters.web.dependencies import service
from app.adapters.web.headers import SERVICE
from app.core.extras.ports import ReportStore
from app.core.extras.statistics import Statistics
from app.core.ports import StorageError

logger = logging.getLogger(__name__)

router = APIRouter()

StatisticsDep = Annotated[Statistics, Depends(service(STATISTICS))]
ReportsDep = Annotated[ReportStore, Depends(service(REPORTS))]
EXPORT_HEADERS = {**SERVICE, "Content-Disposition": "attachment; filename=participants.csv"}


def _unavailable() -> JSONResponse:
    return JSONResponse({"status": "unavailable"}, status_code=503, headers=SERVICE)


@router.get("/admin/stats")
def stats(_: AdminDep, statistics: StatisticsDep) -> JSONResponse:
    try:
        numbers = statistics.current()
    except StorageError:
        return _unavailable()
    return JSONResponse(
        {
            "total": numbers.total,
            "last_24h": numbers.last_24h,
            "failed_emails": numbers.failed_emails,
            "telegram_linked": numbers.telegram_linked,
            "channel_members": numbers.channel_members,
        },
        headers=SERVICE,
    )


@router.get("/admin/export.csv")
def export_csv(_: AdminDep, reports: ReportsDep) -> Response:
    try:
        rows = reports.export_rows()
    except StorageError:
        return _unavailable()
    logger.info("Participants exported: %d rows", len(rows))
    return Response(to_csv(rows), media_type="text/csv", headers=EXPORT_HEADERS)
