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


# ---------------------------------------------------------------------------
# Plans shaped with Aquila: the model's draft is validated before it is used
# ---------------------------------------------------------------------------
from app.plan import PlanDraft, PlanSection, build_custom_plan, expand_sections, plan_title, plan_today  # noqa: E402


def test_sections_expand_to_real_chapters_in_order():
    refs = expand_sections(
        [
            PlanSection(book="Psalm", first_chapter=23),
            PlanSection(book="Jude"),
            PlanSection(book="1 Cor", first_chapter=12, last_chapter=13),
        ]
    )
    assert refs == ["Psalms 23", "Jude 1", "1 Corinthians 12", "1 Corinthians 13"]


def test_unknown_books_are_dropped_and_ranges_clamped_to_the_book():
    refs = expand_sections(
        [
            PlanSection(book="Hezekiah", first_chapter=1),
            PlanSection(book="Philippians", first_chapter=3, last_chapter=40),
            PlanSection(book="Song of Songs", first_chapter=9),
        ]
    )
    assert refs == ["Philippians 3", "Philippians 4", "Song of Solomon 8"]


def test_a_chapter_named_twice_is_read_once():
    refs = expand_sections([PlanSection(book="John", first_chapter=1, last_chapter=2), PlanSection(book="John", first_chapter=2)])
    assert refs == ["John 1", "John 2"]


def test_custom_plan_never_has_an_empty_day():
    draft = PlanDraft(title="Short and sweet", overview="Two sentences.", days=30, sections=[PlanSection(book="Ruth")])
    plan = build_custom_plan(draft, date(2026, 11, 4))
    assert len(plan.schedule) == 4
    assert all(day.references for day in plan.schedule)


def test_custom_plan_with_no_real_chapters_is_refused():
    draft = PlanDraft(title="Nothing", overview="", days=7, sections=[PlanSection(book="Hezekiah")])
    with pytest.raises(ValueError):
        build_custom_plan(draft, date(2026, 11, 4))


def test_custom_plan_text_never_carries_an_em_dash():
    draft = PlanDraft(title="Gospels \u2014 a month", overview="Read slowly \u2014 and often.", days=4, sections=[PlanSection(book="Mark", first_chapter=1, last_chapter=4)])
    plan = build_custom_plan(draft, date(2026, 11, 4))
    assert "\u2014" not in plan.title and "\u2014" not in plan.overview


def test_plan_title_prefers_stored_title_then_describes_the_shape():
    whole = {"days": 365, "schedule": [{"references": [r]} for d in generate_schedule(date(2026, 1, 1), 365) for r in d.references]}
    assert plan_title(whole) == "Through the Bible in 365 days"
    assert plan_title({"days": 7, "schedule": [{"references": ["Psalms 1"]}]}) == "A 7-day reading plan"
    assert plan_title({"days": 7, "title": "Psalms for anxious nights", "schedule": []}) == "Psalms for anxious nights"


def test_plan_today_includes_the_title():
    row = {"id": "p1", "start_date": "2026-11-01", "days": 2, "title": "Two days", "schedule": [{"references": ["Ruth 1"]}, {"references": ["Ruth 2"]}]}
    assert plan_today(row, date(2026, 11, 2))["title"] == "Two days"
