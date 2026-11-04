"""app/plan.py's schedule generator is pure arithmetic over a fixed chapter
count, so a wrong distribution is exactly the kind of off-by-one bug a code
read misses and a test catches immediately.
"""

from datetime import date

import pytest

from app.plan import BOOK_CHAPTER_COUNTS, TOTAL_CHAPTERS, generate_schedule


def test_book_chapter_counts_are_the_full_66_book_canon():
    assert len(BOOK_CHAPTER_COUNTS) == 66
    assert TOTAL_CHAPTERS == 1189


def test_schedule_covers_every_chapter_exactly_once():
    schedule = generate_schedule(date(2026, 1, 1), 365)
    all_refs = [ref for day in schedule for ref in day.references]
    assert len(all_refs) == TOTAL_CHAPTERS
    assert len(set(all_refs)) == TOTAL_CHAPTERS
    assert all_refs[0] == "Genesis 1"
    assert all_refs[-1] == "Revelation 22"


def test_schedule_dates_increment_daily_from_start():
    schedule = generate_schedule(date(2026, 3, 1), 30)
    assert schedule[0].date == date(2026, 3, 1)
    assert schedule[1].date == date(2026, 3, 2)
    assert schedule[-1].date == date(2026, 3, 30)


def test_schedule_length_matches_days_requested():
    schedule = generate_schedule(date(2026, 1, 1), 90)
    assert len(schedule) == 90
    assert [d.day for d in schedule] == list(range(1, 91))


def test_remainder_chapters_spread_across_early_days_not_dumped_on_last():
    # 1189 // 365 = 3 remainder 94: the first 94 days get 4 chapters, the rest get 3.
    schedule = generate_schedule(date(2026, 1, 1), 365)
    assert len(schedule[0].references) == 4
    assert len(schedule[93].references) == 4
    assert len(schedule[94].references) == 3
    assert len(schedule[-1].references) == 3


def test_one_day_plan_gets_the_whole_bible():
    schedule = generate_schedule(date(2026, 1, 1), 1)
    assert len(schedule) == 1
    assert len(schedule[0].references) == TOTAL_CHAPTERS


def test_rejects_zero_or_negative_days():
    with pytest.raises(ValueError):
        generate_schedule(date(2026, 1, 1), 0)


def test_rejects_more_days_than_chapters():
    with pytest.raises(ValueError):
        generate_schedule(date(2026, 1, 1), TOTAL_CHAPTERS + 1)
