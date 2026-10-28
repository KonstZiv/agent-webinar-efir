"""The teacher's admin API of the attendance (docs/requirements.md, section 9а).

Behind the admin token (``AdminDep``, checked before anything is built); never cached or
indexed. A database failure of any kind is 503 ``{"status": "unavailable"}``. The responses
hold personal data: the log gets counts only, no address, code or question.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.adapters.checkin.keys import ATTENDANCE
from app.adapters.web.admin_auth import AdminDep
from app.adapters.web.dependencies import service
from app.adapters.web.headers import SERVICE
from app.core.checkin.model import (
    DEFAULT_WINDOW_MINUTES,
    GROUP_CODE_PATTERN,
    MAX_WINDOW_MINUTES,
    MIN_WINDOW_MINUTES,
    Checkin,
    Entry,
)
from app.core.checkin.service import Attendance
from app.core.ports import StorageError

router = APIRouter()

AttendanceDep = Annotated[Attendance, Depends(service(ATTENDANCE))]
MAX_ID = 2**63 - 1
CheckinId = Annotated[int, Path(ge=1, le=MAX_ID)]
GroupCode = Annotated[str, Path(pattern=f"^{GROUP_CODE_PATTERN}$")]


class OpenCheckin(BaseModel):
    lesson_date: date
    group: Annotated[str | None, Field(pattern=f"^{GROUP_CODE_PATTERN}$")] = None
    window_minutes: Annotated[int, Field(ge=MIN_WINDOW_MINUTES, le=MAX_WINDOW_MINUTES)] = (
        DEFAULT_WINDOW_MINUTES
    )


class Members(BaseModel):
    emails: list[str]


def _unavailable() -> JSONResponse:
    return JSONResponse({"status": "unavailable"}, status_code=503, headers=SERVICE)


def _not_found() -> JSONResponse:
    return JSONResponse({"status": "not_found"}, status_code=404, headers=SERVICE)


def _checkin(checkin: Checkin) -> dict[str, object]:
    return {
        "id": checkin.id,
        "code": checkin.code,
        "lesson_date": checkin.lesson_date.isoformat(),
        "group": checkin.group,
        "opened_at": checkin.opened_at.isoformat(),
        "closes_at": checkin.closes_at.isoformat(),
    }


def _entry(entry: Entry) -> dict[str, object]:
    return {
        "email": entry.email,
        "source": entry.source,
        "rating": entry.rating,
        "question": entry.question,
        "at": entry.at.isoformat(),
    }


@router.post("/admin/checkins")
def open_checkin(_: AdminDep, body: OpenCheckin, attendance: AttendanceDep) -> JSONResponse:
    try:
        checkin = attendance.open(body.lesson_date, body.group, body.window_minutes)
    except StorageError:
        return _unavailable()
    return JSONResponse(_checkin(checkin), status_code=201, headers=SERVICE)


@router.post("/admin/checkins/{checkin_id}/close")
def close_checkin(_: AdminDep, checkin_id: CheckinId, attendance: AttendanceDep) -> JSONResponse:
    try:
        checkin = attendance.close(checkin_id)
    except StorageError:
        return _unavailable()
    if checkin is None:
        return _not_found()
    return JSONResponse(_checkin(checkin), headers=SERVICE)


@router.get("/admin/checkins")
def list_checkins(_: AdminDep, attendance: AttendanceDep) -> JSONResponse:
    try:
        listed = attendance.listed()
    except StorageError:
        return _unavailable()
    return JSONResponse(
        [{**_checkin(line.checkin), "attended": line.attended} for line in listed],
        headers=SERVICE,
    )


@router.get("/admin/checkins/{checkin_id}")
def read_checkin(_: AdminDep, checkin_id: CheckinId, attendance: AttendanceDep) -> JSONResponse:
    try:
        report = attendance.report(checkin_id)
    except StorageError:
        return _unavailable()
    if report is None:
        return _not_found()
    return JSONResponse(
        {
            **_checkin(report.checkin),
            "attended": report.attended,
            "ratings": {str(rating): count for rating, count in report.ratings.items()},
            "average": report.average,
            "entries": [_entry(entry) for entry in report.entries],
        },
        headers=SERVICE,
    )


@router.put("/admin/groups/{code}/members")
def assign_members(
    _: AdminDep, code: GroupCode, body: Members, attendance: AttendanceDep
) -> JSONResponse:
    try:
        members = attendance.assign(code, body.emails)
    except StorageError:
        return _unavailable()
    return JSONResponse(
        {"added": members.added, "unknown": list(members.unknown)}, headers=SERVICE
    )


@router.get("/admin/groups")
def list_groups(_: AdminDep, attendance: AttendanceDep) -> JSONResponse:
    try:
        sizes = attendance.group_sizes()
    except StorageError:
        return _unavailable()
    return JSONResponse(sizes, headers=SERVICE)
