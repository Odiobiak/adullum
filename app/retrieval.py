"""Hybrid retrieval: exact reference lookup + vector similarity + keyword search.

Bible Q&A has three very different query shapes that a single vector search
handles poorly:
  1. "What does John 3:16 say?"        -> exact reference, no ambiguity
  2. "What does propitiation mean?"    -> exact word, full-text search wins
  3. "Where does Paul talk about hope in suffering?" -> conceptual, needs vectors

Rather than force all three through one path, `hybrid_retrieve` tries the cheap,
precise one first (reference regex) and falls back to vector + keyword, merged.
"""

import logging
import re
from dataclasses import dataclass

from openai import OpenAI
from postgrest.exceptions import APIError

from app.config import settings
from app.db import get_supabase
from app.schemas import Verse

log = logging.getLogger(__name__)

_openai = OpenAI(api_key=settings.openai_api_key)

# Canonical book name -> common aliases seen in natural-language queries.
# Not exhaustive of every scholarly abbreviation — covers the forms people
# actually type when chatting with an app.
BOOK_ALIASES: dict[str, list[str]] = {
    "Genesis": ["gen", "ge"], "Exodus": ["exo", "ex"], "Leviticus": ["lev", "le"],
    "Numbers": ["num", "nu"], "Deuteronomy": ["deut", "dt"], "Joshua": ["josh", "jos"],
    "Judges": ["judg", "jdg"], "Ruth": ["ru"], "1 Samuel": ["1 sam", "1sam", "1sa"],
    "2 Samuel": ["2 sam", "2sam", "2sa"], "1 Kings": ["1 kgs", "1kgs", "1ki"],
    "2 Kings": ["2 kgs", "2kgs", "2ki"], "1 Chronicles": ["1 chr", "1chr"],
    "2 Chronicles": ["2 chr", "2chr"], "Ezra": ["ezr"], "Nehemiah": ["neh"],
    "Esther": ["esth", "est"], "Job": ["job"], "Psalms": ["psalm", "ps", "psa"],
    "Proverbs": ["prov", "pr"], "Ecclesiastes": ["eccl", "ecc"],
    "Song of Solomon": ["song", "sos"], "Isaiah": ["isa"], "Jeremiah": ["jer"],
    "Lamentations": ["lam"], "Ezekiel": ["ezek", "eze"], "Daniel": ["dan"],
    "Hosea": ["hos"], "Joel": ["joel"], "Amos": ["amos"], "Obadiah": ["obad", "oba"],
    "Jonah": ["jonah", "jon"], "Micah": ["mic"], "Nahum": ["nah"],
    "Habakkuk": ["hab"], "Zephaniah": ["zeph", "zep"], "Haggai": ["hag"],
    "Zechariah": ["zech", "zec"], "Malachi": ["mal"],
    "Matthew": ["matt", "mt"], "Mark": ["mk", "mrk"], "Luke": ["lk", "luk"],
    "John": ["jn", "jhn"], "Acts": ["acts"], "Romans": ["rom"],
    "1 Corinthians": ["1 cor", "1cor", "1co"], "2 Corinthians": ["2 cor", "2cor", "2co"],
    "Galatians": ["gal"], "Ephesians": ["eph"], "Philippians": ["phil", "php"],
    "Colossians": ["col"], "1 Thessalonians": ["1 thess", "1thess", "1th"],
    "2 Thessalonians": ["2 thess", "2thess", "2th"], "1 Timothy": ["1 tim", "1tim"],
    "2 Timothy": ["2 tim", "2tim"], "Titus": ["titus", "tit"], "Philemon": ["philem", "phm"],
    "Hebrews": ["heb"], "James": ["jas"], "1 Peter": ["1 pet", "1pet", "1pe"],
    "2 Peter": ["2 pet", "2pet", "2pe"], "1 John": ["1 jn", "1john", "1jn"],
    "2 John": ["2 jn", "2john", "2jn"], "3 John": ["3 jn", "3john", "3jn"],
    "Jude": ["jude"], "Revelation": ["rev"],
}

_ALIAS_TO_CANONICAL = {
    alias.replace(" ", "").lower(): canonical
    for canonical, aliases in BOOK_ALIASES.items()
    for alias in aliases + [canonical]
}

# Names that only ever arrive as whole book names (from a model building a
# reading plan, say), never inside a typed reference, so they live here
# rather than in BOOK_ALIASES where the reference regex would have to match them.
_ALIAS_TO_CANONICAL.update({"songofsongs": "Song of Solomon", "canticles": "Song of Solomon", "revelations": "Revelation"})


def canonical_book(name: str) -> str | None:
    """Resolve a book name as a person or a model might write it ("Psalm",
    "1 Cor", "Song of Songs") to its canonical name, or None if it isn't a
    book of the 66-book canon."""
    key = re.sub(r"[\s.]", "", name or "").lower()
    return _ALIAS_TO_CANONICAL.get(key)


_REFERENCE_RE = re.compile(
    r"\b(?P<book>[1-3]?\s?[A-Za-z]+)\s+(?P<chapter>\d{1,3})"
    r"(?::(?P<vstart>\d{1,3})(?:[-–](?P<vend>\d{1,3}))?)?"
)
_SONG_OF_RE = re.compile(r"\bsong\s+of\s+(?:solomon|songs)\b", re.IGNORECASE)

# Matches "(the) book of James", "book of 1 Corinthians", etc. — deliberately
# narrower than matching any bare book name (which would false-positive on
# common words/names that are also book names: Job, Mark, Acts, Titus, James,
# John, Ruth...). Only triggers on this explicit phrasing, which is exactly
# how people ask book-level questions ("give me a starting point for studying
# the book of James") that parse_reference's chapter-number requirement misses.
_BOOK_OF_RE = re.compile(r"\bbook of\s+([1-3]?\s?[A-Za-z]+)", re.IGNORECASE)


def parse_book_mention(query: str) -> str | None:
    """Find a bare book-level mention with no chapter/verse attached, so
    retrieval can scope to that book instead of drifting across the whole
    corpus on a book-overview question parse_reference doesn't match."""
    match = _BOOK_OF_RE.search(query)
    if not match:
        return None
    key = match.group(1).replace(" ", "").lower()
    return _ALIAS_TO_CANONICAL.get(key)


@dataclass
class ParsedReference:
    book: str
    chapter: int
    verse_start: int | None
    verse_end: int | None


def parse_reference(query: str) -> ParsedReference | None:
    """Find the first Bible-reference-shaped substring in `query` and resolve it
    against BOOK_ALIASES, e.g. "what does jn 3:16 mean" -> John 3:16-16.

    Returns None if no substring both matches the reference shape (book + chapter
    [+ verse[-range]]) AND resolves to a known book alias — a query like "chapter 3
    of that book" matches the regex's chapter part but has no recognizable book
    name, so it correctly falls through to vector/keyword search instead.

    "Song of Solomon 2:1" is the one canonical name with spaces in the middle,
    which the single-word book group can't match, so it is shortened to the
    "Song" alias first.
    """
    found = find_references(query)
    return found[0] if found else None


def find_references(text: str) -> list[ParsedReference]:
    """Every Bible reference in `text`, in order, resolved the same way as
    parse_reference. Used to check that a reply only names verses it was given
    (app/agent/nodes.py::listen)."""
    text = _SONG_OF_RE.sub("Song", text)
    found = []
    for match in _REFERENCE_RE.finditer(text):
        key = match.group("book").replace(" ", "").lower()
        canonical = _ALIAS_TO_CANONICAL.get(key)
        if not canonical:
            continue
        vstart = match.group("vstart")
        vend = match.group("vend")
        found.append(
            ParsedReference(
                book=canonical,
                chapter=int(match.group("chapter")),
                verse_start=int(vstart) if vstart else None,
                verse_end=int(vend) if vend else (int(vstart) if vstart else None),
            )
        )
    return found


def embed_query(text: str) -> list[float]:
    """Embed a single query string with the same model and dimension used at
    ingest time (scripts/ingest.py). Vector search only works if query and
    corpus embeddings come from the same model and dimension.
    """
    resp = _openai.embeddings.create(
        model=settings.embedding_model, input=text, dimensions=settings.embedding_dim
    )
    return resp.data[0].embedding


def lookup_by_reference(ref: ParsedReference, translation: str) -> list[Verse]:
    """Direct, exact-match DB lookup for a parsed reference — no embeddings involved.
    Cheapest and most precise of the three retrieval paths; used whenever
    `parse_reference` finds a reference in the query.
    """
    query = (
        get_supabase()
        .table("verses")
        .select("book, chapter, verse, text, translation")
        .eq("translation", translation)
        .eq("book", ref.book)
        .eq("chapter", ref.chapter)
    )
    if ref.verse_start is not None:
        query = query.gte("verse", ref.verse_start).lte("verse", ref.verse_end)
    rows = query.order("verse").execute().data
    return [Verse(**row, source="reference") for row in rows]


def lookup_book_start(book: str, translation: str, k: int = 8) -> list[Verse]:
    """Direct DB lookup of a book's opening verses — the natural grounding for
    a book-overview question ("give me a starting point for studying James")
    that names a book but no chapter, so parse_reference can't handle it and a
    plain semantic search would drift across the whole corpus instead of
    staying inside the one book actually asked about.
    """
    rows = (
        get_supabase()
        .table("verses")
        .select("book, chapter, verse, text, translation")
        .eq("translation", translation)
        .eq("book", book)
        .order("chapter")
        .order("verse")
        .limit(k)
        .execute()
        .data
    )
    return [Verse(**row, source="reference") for row in rows]


def vector_search(query: str, translation: str, k: int = 8) -> list[Verse]:
    """Semantic search via the `match_verses` Postgres function (supabase/schema.sql),
    which does the cosine-distance ordering in the database rather than pulling
    every embedding over the wire to rank client-side.

    Only `settings.search_translation` stores embeddings. `match_verses` finds
    the nearest verses there and returns the same verses from `translation`, so
    this works for any loaded translation.
    """
    embedding = embed_query(query)
    rows = (
        get_supabase()
        .rpc(
            "match_verses",
            {"query_embedding": embedding, "match_translation": translation, "match_count": k},
        )
        .execute()
        .data
    )
    return [Verse(**row, translation=translation, source="vector") for row in rows]


def keyword_search(query: str, translation: str, k: int = 8) -> list[Verse]:
    """Full-text search over the generated `tsv` column — catches exact-word
    queries ("what does propitiation mean") that vector search can under-rank
    because the embedding pulls toward the surrounding topic rather than the
    specific term.
    """
    rows = (
        get_supabase()
        .table("verses")
        .select("book, chapter, verse, text, translation")
        .eq("translation", translation)
        # limit() has to come before text_search(): postgrest-py's text_search
        # returns a builder that no longer offers limit().
        .limit(k)
        # "web_search" (with the underscore) maps to Postgres's
        # websearch_to_tsquery, which accepts a whole sentence. Any other value
        # is silently ignored and falls back to to_tsquery, which rejects
        # anything but a single word or explicit tsquery syntax.
        .text_search("tsv", query, options={"type": "web_search"})
        .execute()
        .data
    )
    return [Verse(**row, source="keyword") for row in rows]


def hybrid_retrieve(query: str, translation: str, k: int = 8) -> list[Verse]:
    """Merge all three retrieval paths, reference results first, deduped by
    (book, chapter, verse), capped at `k`.

    Reference hits go first because they're unambiguous matches to what the user
    asked for; keyword search only runs to top up the list if vector search
    didn't already fill it, since vector search alone usually covers thematic
    queries fine and an extra DB round-trip is wasted otherwise.
    """
    results: list[Verse] = []
    seen: set[tuple[str, int, int]] = set()

    def add(verses: list[Verse]) -> None:
        for v in verses:
            key = (v.book, v.chapter, v.verse)
            if key not in seen:
                seen.add(key)
                results.append(v)

    ref = parse_reference(query)
    if ref:
        add(lookup_by_reference(ref, translation))
    else:
        book = parse_book_mention(query)
        if book:
            add(lookup_book_start(book, translation, k=k))

    # Vector search is the one path that can be slow (a full scan of every
    # embedding when the index is missing or stale), and Postgres cancels it at
    # the statement timeout. Losing it costs some recall on thematic questions,
    # but the reference and keyword paths still find verses, which is far
    # better than the whole answer failing with nothing on screen.
    try:
        add(vector_search(query, translation, k=k))
    except APIError as error:
        log.warning("Vector search failed, falling back to keyword search: %s", error.message)

    if len(results) < k:
        add(keyword_search(query, translation, k=k - len(results)))

    return results[:k]
