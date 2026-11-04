"""Deterministic Bible reading plan scheduling.

Splits the 1189 chapters of the 66-book Protestant canon across N days as
evenly as possible, straight through in canonical order (Genesis to
Revelation). This is pure arithmetic, no LLM call and no database, which is
what keeps it cheap enough to regenerate on every request and easy to unit
test (see tests/test_plan.py). Chronological or thematic ordering is a
documented future option in docs/cognigy-xapp-features.md, it needs a curated
chapter-ordering table this module doesn't build yet.

generate_overview is the one LLM call the whole plan gets, a short written
introduction, not a per-day call, since asking the full LangGraph agent (or
an LLM) for 365 separate reflections would be both slow and expensive for
something that is fundamentally a fixed reading schedule.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from app.config import settings

# Canonical order and chapter counts for the 66-book Protestant canon, the
# same versification (1189 chapters total) that KJV, WEB, ASV, and BSB all
# share, so this table is translation-independent.
BOOK_CHAPTER_COUNTS: dict[str, int] = {
    "Genesis": 50, "Exodus": 40, "Leviticus": 27, "Numbers": 36, "Deuteronomy": 34,
    "Joshua": 24, "Judges": 21, "Ruth": 4, "1 Samuel": 31, "2 Samuel": 24,
    "1 Kings": 22, "2 Kings": 25, "1 Chronicles": 29, "2 Chronicles": 36,
    "Ezra": 10, "Nehemiah": 13, "Esther": 10, "Job": 42, "Psalms": 150,
    "Proverbs": 31, "Ecclesiastes": 12, "Song of Solomon": 8, "Isaiah": 66,
    "Jeremiah": 52, "Lamentations": 5, "Ezekiel": 48, "Daniel": 12, "Hosea": 14,
    "Joel": 3, "Amos": 9, "Obadiah": 1, "Jonah": 4, "Micah": 7, "Nahum": 3,
    "Habakkuk": 3, "Zephaniah": 3, "Haggai": 2, "Zechariah": 14, "Malachi": 4,
    "Matthew": 28, "Mark": 16, "Luke": 24, "John": 21, "Acts": 28, "Romans": 16,
    "1 Corinthians": 16, "2 Corinthians": 13, "Galatians": 6, "Ephesians": 6,
    "Philippians": 4, "Colossians": 4, "1 Thessalonians": 5, "2 Thessalonians": 3,
    "1 Timothy": 6, "2 Timothy": 4, "Titus": 3, "Philemon": 1, "Hebrews": 13,
    "James": 5, "1 Peter": 5, "2 Peter": 3, "1 John": 5, "2 John": 1,
    "3 John": 1, "Jude": 1, "Revelation": 22,
}

BOOK_ORDER: list[str] = list(BOOK_CHAPTER_COUNTS)

TOTAL_CHAPTERS = sum(BOOK_CHAPTER_COUNTS.values())  # 1189

_llm = ChatOpenAI(model=settings.chat_model, api_key=settings.openai_api_key, temperature=0.4)


@dataclass
class ScheduleDay:
    day: int
    date: date
    references: list[str]


def _all_chapters() -> list[str]:
    """Every chapter reference in canonical order: Genesis 1, Genesis 2, ..., Revelation 22."""
    return [
        f"{book} {chapter}"
        for book in BOOK_ORDER
        for chapter in range(1, BOOK_CHAPTER_COUNTS[book] + 1)
    ]


def generate_schedule(start_date: date, days: int) -> list[ScheduleDay]:
    """Split the whole Bible across `days`, straight through in canonical order.

    The remainder (TOTAL_CHAPTERS % days) is spread one extra chapter per day
    across the first N days rather than dumped on the last day, so no single
    day of the plan is disproportionately long.
    """
    if days < 1:
        raise ValueError("days must be at least 1")
    if days > TOTAL_CHAPTERS:
        raise ValueError(
            f"days ({days}) can't exceed the Bible's {TOTAL_CHAPTERS} chapters, "
            "every day needs at least one chapter to read"
        )

    chapters = _all_chapters()
    base, remainder = divmod(TOTAL_CHAPTERS, days)

    schedule: list[ScheduleDay] = []
    cursor = 0
    for i in range(days):
        count = base + (1 if i < remainder else 0)
        schedule.append(
            ScheduleDay(
                day=i + 1,
                date=start_date + timedelta(days=i),
                references=chapters[cursor : cursor + count],
            )
        )
        cursor += count

    return schedule


def generate_overview(start_date: date, days: int, translation: str) -> str:
    """One short, warm introduction to the whole plan, not a per-day reflection."""
    prompt = (
        f"Write two short, warm sentences introducing a {days}-day Bible reading plan "
        f"that starts on {start_date.isoformat()} and reads straight through the whole "
        f"Bible in the {translation} translation. No preamble, no markdown, just the "
        "two sentences."
    )
    response = _llm.invoke([HumanMessage(content=prompt)])
    return response.content.strip()
