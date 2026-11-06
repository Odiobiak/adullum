"""The person's local week: Monday first, which days can be marked."""

from datetime import date

import pytest
from fastapi import HTTPException

from app import days

TODAY = date(2026, 11, 5)  # a Thursday


def test_the_week_runs_monday_to_sunday():
    week = days.this_week(TODAY)
    assert week[0] == date(2026, 11, 2) and week[-1] == date(2026, 11, 8)


def test_marks_say_what_was_done_and_what_is_still_to_come():
    marks = days.week_marks({date(2026, 11, 3)}, TODAY)
    assert [m["label"] for m in marks] == ["M", "T", "W", "T", "F", "S", "S"]
    assert marks[1]["done"] and marks[3]["today"] and marks[4]["future"] and not marks[3]["future"]


def test_only_the_last_week_can_be_marked():
    assert days.parse_markable_day(None, TODAY) == TODAY
    assert days.parse_markable_day("2026-10-30", TODAY) == date(2026, 10, 30)
    for day in ("2026-11-06", "2026-10-29", "soon"):
        with pytest.raises(HTTPException):
            days.parse_markable_day(day, TODAY)
