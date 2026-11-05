"""Bible reading plans: scheduling, progress, and plans shaped with Aquila.

Two kinds of plan share one shape (a list of days, each with chapter
references):

- Whole-Bible plans (`generate_schedule`) split the 1189 chapters of the
  66-book Protestant canon across N days, straight through in canonical order.
  Pure arithmetic, no LLM call and no database, so it is cheap to regenerate
  and easy to unit test (see tests/test_plan.py).
- Plans shaped with Aquila (`draft_custom_plan`) start from a request in the
  person's own words ("the Gospels in a month", "two weeks on anxiety"). The
  model only chooses which books and chapter ranges to read and for how long.
  Every chapter it names is checked against BOOK_CHAPTER_COUNTS, and the split
  into days is the same deterministic arithmetic as a whole-Bible plan, so a
  plan can never send someone to a chapter that doesn't exist.

generate_overview is the one LLM call a whole-Bible plan gets, a short written
introduction rather than a per-day call, since asking for 365 separate
reflections would be slow and expensive for what is a fixed schedule.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.config import settings
from app.retrieval import canonical_book

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

# The longest plan Aquila will shape from a request. Longer than this, the
# whole-Bible plan is the better fit, and it has its own button.
MAX_CUSTOM_DAYS = 365

# House style keeps em dashes out of anything Aquila says; the prompt asks,
# and build_custom_plan makes sure.
_EM_DASH = "\u2014"

_llm = ChatOpenAI(model=settings.chat_model, api_key=settings.openai_api_key, temperature=0.4)


@dataclass
class ScheduleDay:
    day: int
    date: date
    references: list[str]


# ---------------------------------------------------------------------------
# Scheduling (pure, unit tested)
# ---------------------------------------------------------------------------
def _all_chapters() -> list[str]:
    """Every chapter reference in canonical order: Genesis 1, Genesis 2, ..., Revelation 22."""
    return [
        f"{book} {chapter}"
        for book in BOOK_ORDER
        for chapter in range(1, BOOK_CHAPTER_COUNTS[book] + 1)
    ]


def split_into_days(chapters: list[str], start_date: date, days: int) -> list[ScheduleDay]:
    """Spread `chapters`, in order, across `days` as evenly as possible.

    The remainder (len(chapters) % days) goes one extra chapter per day across
    the first days rather than all on the last, so no single day is
    disproportionately long.
    """
    if days < 1:
        raise ValueError("days must be at least 1")
    if days > len(chapters):
        raise ValueError(
            f"days ({days}) can't exceed the {len(chapters)} chapters in the plan, "
            "every day needs at least one chapter to read"
        )

    base, remainder = divmod(len(chapters), days)
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


def generate_schedule(start_date: date, days: int) -> list[ScheduleDay]:
    """Split the whole Bible across `days`, straight through in canonical order."""
    if days > TOTAL_CHAPTERS:
        raise ValueError(
            f"days ({days}) can't exceed the Bible's {TOTAL_CHAPTERS} chapters, "
            "every day needs at least one chapter to read"
        )
    return split_into_days(_all_chapters(), start_date, days)


def serialize_schedule(schedule: list[ScheduleDay]) -> list[dict]:
    """The JSON shape stored in reading_plans.schedule."""
    return [{"day": d.day, "date": d.date.isoformat(), "references": d.references} for d in schedule]


def plan_title(plan: dict) -> str:
    """A plan's display name. Plans shaped with Aquila store their own title;
    whole-Bible plans (and any row from before the title column existed) get
    one from their shape."""
    if plan.get("title"):
        return plan["title"]
    days = int(plan["days"])
    chapter_count = sum(len(d.get("references") or []) for d in plan.get("schedule") or [])
    if chapter_count in (0, TOTAL_CHAPTERS):
        return f"Through the Bible in {days} days"
    return f"A {days}-day reading plan"


def plan_today(plan: dict, today: date) -> dict:
    """Where a plan stands on `today`: the day number, that day's readings,
    and overall progress. Before the start date it shows day 1; after the end
    it holds on the last day."""
    start = date.fromisoformat(str(plan["start_date"]))
    days = int(plan["days"])
    day = min(max((today - start).days + 1, 1), days)
    schedule = plan.get("schedule") or []
    refs = schedule[day - 1]["references"] if len(schedule) >= day else []
    completed = sorted(set(plan.get("completed_days") or []))
    return {
        "id": plan["id"],
        "title": plan_title(plan),
        "days": days,
        "day": day,
        "refs": refs,
        "done_today": day in completed,
        "completed": len(completed),
        "progress_pct": round(100 * len(completed) / days, 1) if days else 0,
    }


# ---------------------------------------------------------------------------
# Plans shaped with Aquila
# ---------------------------------------------------------------------------
class PlanSection(BaseModel):
    """One stretch of reading: a whole book, or a run of its chapters."""

    book: str = Field(description="A book of the 66-book Protestant canon, by its usual English name, e.g. 'Psalms' or '1 Corinthians'.")
    first_chapter: int | None = Field(default=None, description="First chapter to read. Leave empty to read the whole book.")
    last_chapter: int | None = Field(default=None, description="Last chapter to read. Leave empty for just first_chapter, or the whole book if both are empty.")


class PlanDraft(BaseModel):
    """What the model returns when shaping a plan from a request."""

    title: str = Field(description="A short, plain name for the plan, at most six words.")
    overview: str = Field(description="Two warm sentences, addressed to the reader, on what they'll read and why.")
    days: int = Field(description="How many days the plan takes.")
    sections: list[PlanSection] = Field(description="What to read, in reading order.")


PLAN_SYSTEM_PROMPT = """You are Aquila, a warm Bible study companion, helping someone shape a \
reading plan from a request in their own words.

Choose what they should read, in the order to read it, and how many days it should take.
- Use only books of the 66-book Protestant canon.
- Give each section as a book with a chapter range, or no chapters at all for the whole book.
- Choose at least one chapter for every day of the plan, and no more than about four a day.
- If they name a length, use it. If not, choose something sustainable, usually 7 to 60 days, \
and never more than 365.
- For a topic or a season of life rather than a book, choose the chapters that speak to it most \
directly, from both testaments where that fits.
- If the request isn't about reading the Bible at all, make a gentle 7-day plan from the Psalms \
and the Gospels.

The title is short and plain, in sentence case, like "The Gospels in 30 days" or \
"Psalms for anxious nights". The overview is two short sentences that speak to them \
directly, the way a friend who knows the Bible would. Say what they'll read and why it \
fits what they asked. Avoid brochure phrases like "this plan will guide you", "journey" \
or "deepen your understanding". Don't quote any verses, don't use markdown, and never \
use an em dash."""


def expand_sections(sections: list[PlanSection]) -> list[str]:
    """Turn the model's sections into real chapter references, in order.

    Book names are resolved through the same aliases retrieval uses, chapter
    ranges are clamped to the book's real length, unknown books are dropped,
    and a chapter named twice is read once (where it first appears).
    """
    chapters: list[str] = []
    seen: set[str] = set()
    for section in sections:
        book = canonical_book(section.book)
        if not book:
            continue
        count = BOOK_CHAPTER_COUNTS[book]
        first = section.first_chapter or 1
        last = section.last_chapter or (section.first_chapter or count)
        first, last = max(1, min(first, count)), max(1, min(last, count))
        if last < first:
            first, last = last, first
        for chapter in range(first, last + 1):
            ref = f"{book} {chapter}"
            if ref not in seen:
                seen.add(ref)
                chapters.append(ref)
    return chapters


@dataclass
class CustomPlan:
    title: str
    overview: str
    schedule: list[ScheduleDay]


def build_custom_plan(draft: PlanDraft, start_date: date) -> CustomPlan:
    """Validate a draft and lay it out over days. Raises ValueError when the
    draft names no real chapters. The day count is clamped so every day has
    at least one chapter, which can make a plan shorter than requested."""
    chapters = expand_sections(draft.sections)
    if not chapters:
        raise ValueError("The plan didn't include any chapters of the Bible.")
    days = max(1, min(draft.days, MAX_CUSTOM_DAYS, len(chapters)))
    title = " ".join(draft.title.replace(_EM_DASH, ",").split())[:80] or f"A {days}-day reading plan"
    overview = draft.overview.replace(_EM_DASH, ",").strip()
    return CustomPlan(title=title, overview=overview, schedule=split_into_days(chapters, start_date, days))


def draft_custom_plan(request: str, start_date: date) -> CustomPlan:
    """Ask the model to shape a plan from `request`, then validate it."""
    structured = _llm.with_structured_output(PlanDraft)
    draft: PlanDraft = structured.invoke(
        [SystemMessage(PLAN_SYSTEM_PROMPT), HumanMessage(f"Their request: {request.strip()}")]
    )
    return build_custom_plan(draft, start_date)


def generate_overview(start_date: date, days: int, translation: str) -> str:
    """One short, warm introduction to a whole-Bible plan, not a per-day reflection."""
    prompt = (
        f"Write two short, warm sentences introducing a {days}-day Bible reading plan "
        f"that starts on {start_date.isoformat()} and reads straight through the whole "
        f"Bible in the {translation} translation. No preamble, no markdown, no em dashes, "
        "just the two sentences."
    )
    response = _llm.invoke([HumanMessage(content=prompt)])
    return response.content.strip()
