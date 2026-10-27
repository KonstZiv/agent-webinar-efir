"""Helpers of the attendance tests. Addresses are ``…@example.com`` only."""

from dataclasses import dataclass

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.adapters.db.models import Attendance, Checkin, ParticipantGroup
from tests import copy_oracle as copy
from tests.conftest import REQUIRED_ENV
from tests.fakes import FixedClock

ADMIN = {"Authorization": f"Bearer {REQUIRED_ENV['ADMIN_TOKEN']}"}
HTMX = {"HX-Request": "true"}
LESSON = "2026-11-02"
GROUP = "cbs-2026-10"


@dataclass
class Site:
    client: TestClient
    engine: Engine
    clock: FixedClock

    def admin_post(
        self, path: str, body: dict[str, object] | None = None, *, token: bool = True
    ) -> httpx.Response:
        return self.client.post(path, json=body, headers=ADMIN if token else {})

    def admin_get(self, path: str) -> httpx.Response:
        return self.client.get(path, headers=ADMIN)

    def open(self, **body: object) -> dict[str, object]:
        """Open a check-in through the admin API; its JSON."""
        response = self.admin_post(
            "/admin/checkins", {"lesson_date": LESSON, "group": GROUP, "window_minutes": 20, **body}
        )
        assert response.status_code == 201
        found: dict[str, object] = response.json()
        return found

    def mark(
        self,
        code: str,
        email: str,
        *,
        htmx: bool = True,
        rating: str = "",
        question: str = "",
    ) -> httpx.Response:
        data = {"code": code, "email": email, "rating": rating, "question": question}
        return self.client.post("/checkin", data=data, headers=HTMX if htmx else {})

    def attendance(self) -> list[Attendance]:
        with Session(self.engine) as session:
            return list(session.scalars(select(Attendance).order_by(Attendance.id)))

    def checkins(self) -> list[Checkin]:
        with Session(self.engine) as session:
            return list(session.scalars(select(Checkin).order_by(Checkin.id)))

    def members(self) -> list[tuple[int, str]]:
        with Session(self.engine) as session:
            rows = session.scalars(select(ParticipantGroup).order_by(ParticipantGroup.id))
            return [(row.participant_id, row.group_code) for row in rows]


# --- texts: docs/copy.md 14.1, read by the test itself ---------------------------------------


def page_texts() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """The labelled lines, the fields table and the errors table of docs/copy.md, 14.1.

    The values ``{…}`` stay as written (``raw_copy_text``): the success line is put together by
    the test from the date of the check-in.
    """
    lines = copy.section("14.1", copy.raw_copy_text()).splitlines()
    marks = {line.strip(): number for number, line in enumerate(lines)}
    fields = "\n".join(lines[marks["Поля і підписи:"] : marks["Успіх:"]])
    success = "\n".join(lines[marks["Успіх:"] : marks["Помилки:"]])
    errors = "\n".join(lines[marks["Помилки:"] :])
    labelled = "\n".join(lines[: marks["Поля і підписи:"]])
    shown = {
        "title": copy.one(labelled, "Заголовок"),
        "intro": copy.one(labelled, "Вступ"),
        "success_title": copy.one(success, "Заголовок"),
        "success_text": copy.one(success, "Текст"),
        "success_feedback": copy.one(success, "Текст, якщо передано оцінку або запитання"),
    }
    return shown, copy.table(fields), copy.table(errors)


SHOWN, FIELDS, ERRORS = page_texts()
EMAIL_UNKNOWN = ERRORS["Адреси немає серед зареєстрованих"]
CODE_INVALID = ERRORS["Код не підходить або чек-ін закритий"]
