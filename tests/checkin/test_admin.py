"""The admin API of the attendance (docs/requirements.md, section 9а)."""

from datetime import datetime, timedelta

import pytest

from app.core.checkin.model import CODE_ALPHABET
from tests.checkin.conftest import Site
from tests.checkin.helpers import ADMIN, GROUP, LESSON
from tests.conftest import ParticipantFactory


def moment(value: object) -> datetime:
    return datetime.fromisoformat(str(value))


# --- opening and closing ----------------------------------------------------------------


def test_open_gives_a_code_and_a_window(site: Site) -> None:
    response = site.admin_post(
        "/admin/checkins", {"lesson_date": LESSON, "group": GROUP, "window_minutes": 20}
    )

    body = response.json()
    assert response.status_code == 201
    assert set(body) == {"id", "code", "lesson_date", "group", "opened_at", "closes_at"}
    assert len(body["code"]) == 4 and set(body["code"]) <= set(CODE_ALPHABET)
    assert (body["lesson_date"], body["group"]) == (LESSON, GROUP)
    assert moment(body["closes_at"]) - moment(body["opened_at"]) == timedelta(minutes=20)
    assert response.headers["cache-control"] == "no-store"


def test_defaults_are_twenty_minutes_and_no_group(site: Site) -> None:
    response = site.admin_post("/admin/checkins", {"lesson_date": LESSON})

    body = response.json()
    assert body["group"] is None
    assert moment(body["closes_at"]) - moment(body["opened_at"]) == timedelta(minutes=20)


def test_open_without_the_token_is_401(site: Site) -> None:
    response = site.admin_post(
        "/admin/checkins", {"lesson_date": LESSON, "window_minutes": 20}, token=False
    )

    assert response.status_code == 401
    assert site.checkins() == []


def test_a_bad_body_without_the_token_is_still_401(site: Site) -> None:
    assert site.admin_post("/admin/checkins", {"window_minutes": 0}, token=False).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"lesson_date": LESSON, "window_minutes": 0},
        {"lesson_date": LESSON, "window_minutes": 181},
        {"lesson_date": "not a date"},
        {"window_minutes": 20},
        {"lesson_date": LESSON, "group": "CBS"},
        {"lesson_date": LESSON, "group": "x"},
        {"lesson_date": LESSON, "group": "a" * 33},
    ],
)
def test_a_bad_body_is_422_and_opens_nothing(site: Site, body: dict[str, object]) -> None:
    assert site.admin_post("/admin/checkins", body).status_code == 422
    assert site.checkins() == []


@pytest.mark.parametrize("minutes", [1, 180])
def test_the_edges_of_the_window_are_allowed(site: Site, minutes: int) -> None:
    assert site.admin_post(
        "/admin/checkins", {"lesson_date": LESSON, "window_minutes": minutes}
    ).status_code == 201


def test_open_codes_are_unique(site: Site) -> None:
    codes = {site.open()["code"] for _ in range(30)}

    assert len(codes) == 30


def test_close_sets_closes_at_to_now_and_a_second_close_changes_nothing(site: Site) -> None:
    opened = site.open()
    site.clock.advance(timedelta(minutes=5))

    first = site.admin_post(f"/admin/checkins/{opened['id']}/close")
    site.clock.advance(timedelta(minutes=1))
    second = site.admin_post(f"/admin/checkins/{opened['id']}/close")

    assert first.status_code == second.status_code == 200
    assert moment(first.json()["closes_at"]) == moment(opened["opened_at"]) + timedelta(minutes=5)
    assert second.json() == first.json()


def test_close_of_an_expired_checkin_changes_nothing(site: Site) -> None:
    opened = site.open(window_minutes=1)
    site.clock.advance(timedelta(minutes=10))

    response = site.admin_post(f"/admin/checkins/{opened['id']}/close")

    assert response.json() == opened


def test_an_unknown_id_is_404(site: Site) -> None:
    assert site.admin_post("/admin/checkins/999/close").status_code == 404
    assert site.admin_get("/admin/checkins/999").status_code == 404


def test_close_without_the_token_is_401(site: Site) -> None:
    opened = site.open()

    assert site.admin_post(f"/admin/checkins/{opened['id']}/close", token=False).status_code == 401


# --- reading ----------------------------------------------------------------------------


def test_the_list_counts_the_marks_and_puts_the_latest_first(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant = participant_factory("one@example.com")
    first, second = site.open(), site.open(lesson_date="2026-11-09")
    site.mark(str(first["code"]), participant.email)

    response = site.admin_get("/admin/checkins")

    assert response.status_code == 200
    assert [(line["id"], line["attended"]) for line in response.json()] == [
        (second["id"], 0),
        (first["id"], 1),
    ]
    assert response.json()[1]["code"] == first["code"]


def test_the_report_has_the_counts_the_ratings_and_the_entries(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    people = [participant_factory(f"p{number}@example.com") for number in range(3)]
    opened = site.open()
    code = str(opened["code"])
    site.mark(code, people[0].email, rating="5", question="Коли запис?")
    site.clock.advance(timedelta(minutes=1))
    site.mark(code, people[1].email, rating="4")
    site.mark(code, people[2].email)

    body = site.admin_get(f"/admin/checkins/{opened['id']}").json()

    assert body["attended"] == 3
    assert body["ratings"] == {"1": 0, "2": 0, "3": 0, "4": 1, "5": 1}
    assert body["average"] == 4.5
    assert [(e["email"], e["source"], e["rating"], e["question"]) for e in body["entries"]] == [
        ("p0@example.com", "site", 5, "Коли запис?"),
        ("p1@example.com", "site", 4, None),
        ("p2@example.com", "site", None, None),
    ]
    assert all(moment(entry["at"]) for entry in body["entries"])


def test_an_empty_report_has_no_average(site: Site) -> None:
    opened = site.open()

    body = site.admin_get(f"/admin/checkins/{opened['id']}").json()

    assert (body["attended"], body["average"], body["entries"]) == (0, None, [])


# --- groups -----------------------------------------------------------------------------


def test_members_are_added_once_and_unknown_addresses_are_returned(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant_factory("a@example.com")
    participant_factory("b@example.com")
    body = {"emails": ["A@example.com ", "b@example.com", "nobody@example.com"]}

    first = site.client.put(f"/admin/groups/{GROUP}/members", json=body, headers=ADMIN)
    second = site.client.put(f"/admin/groups/{GROUP}/members", json=body, headers=ADMIN)

    assert first.status_code == 200
    assert first.json() == {"added": 2, "unknown": ["nobody@example.com"]}
    assert second.json() == {"added": 0, "unknown": ["nobody@example.com"]}
    assert len(site.members()) == 2
    assert site.admin_get("/admin/groups").json() == {GROUP: 2}


def test_a_participant_may_be_in_several_groups(
    site: Site, participant_factory: ParticipantFactory
) -> None:
    participant_factory("a@example.com")
    for code in ("cbs-2026-10", "open-2026-10"):
        site.client.put(
            f"/admin/groups/{code}/members", json={"emails": ["a@example.com"]}, headers=ADMIN
        )

    assert site.admin_get("/admin/groups").json() == {"cbs-2026-10": 1, "open-2026-10": 1}


def test_no_groups_is_an_empty_object(site: Site) -> None:
    assert site.admin_get("/admin/groups").json() == {}


@pytest.mark.parametrize("code", ["CBS", "x", "a_b", "a" * 33])
def test_a_bad_group_code_is_422(site: Site, code: str) -> None:
    response = site.client.put(
        f"/admin/groups/{code}/members", json={"emails": []}, headers=ADMIN
    )

    assert response.status_code == 422


def test_group_routes_need_the_token(site: Site) -> None:
    assert site.client.put(f"/admin/groups/{GROUP}/members", json={"emails": []}).status_code == 401
    assert site.client.get("/admin/groups").status_code == 401
    assert site.client.get("/admin/checkins").status_code == 401
    assert site.client.get("/admin/checkins/1").status_code == 401


def test_members_need_a_list(site: Site) -> None:
    response = site.client.put(f"/admin/groups/{GROUP}/members", json={}, headers=ADMIN)

    assert response.status_code == 422
