"""Load a public-domain translation into Supabase: attach book metadata, embed
in batches when it is the search translation, upsert.

Only `settings.search_translation` (BSB) is embedded. Vector search runs over
its embeddings and returns the matching verses of whichever translation was
asked for, so every other translation is stored as text alone, which keeps
the database small and costs no OpenAI calls. Ingest the search translation
first; until it is loaded, vector search finds nothing for any translation.

Expects a JSON file that is a flat list of verse objects:
    [{"book": "Genesis", "chapter": 1, "verse": 1, "text": "In the beginning..."}, ...]

scripts/fetch_translation.py downloads KJV, ASV, WEB, or BSB from a known
public-domain source and writes exactly this shape. For any other source,
verify the license before ingesting; a project going on GitHub should not
bundle a copyrighted translation, and the reader only offers translations
listed in app/bible.py::TRANSLATIONS.

Usage:
    python scripts/fetch_translation.py --translation KJV
    python scripts/ingest.py --file data/kjv.json --translation KJV
"""

import argparse
import json
import sys
import time
from pathlib import Path

from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.db import get_supabase  # noqa: E402

# Canonical 66-book order, matching app/retrieval.py's BOOK_ALIASES keys.
BOOK_ORDER = [
    "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy", "Joshua", "Judges",
    "Ruth", "1 Samuel", "2 Samuel", "1 Kings", "2 Kings", "1 Chronicles",
    "2 Chronicles", "Ezra", "Nehemiah", "Esther", "Job", "Psalms", "Proverbs",
    "Ecclesiastes", "Song of Solomon", "Isaiah", "Jeremiah", "Lamentations",
    "Ezekiel", "Daniel", "Hosea", "Joel", "Amos", "Obadiah", "Jonah", "Micah",
    "Nahum", "Habakkuk", "Zephaniah", "Haggai", "Zechariah", "Malachi",
    "Matthew", "Mark", "Luke", "John", "Acts", "Romans", "1 Corinthians",
    "2 Corinthians", "Galatians", "Ephesians", "Philippians", "Colossians",
    "1 Thessalonians", "2 Thessalonians", "1 Timothy", "2 Timothy", "Titus",
    "Philemon", "Hebrews", "James", "1 Peter", "2 Peter", "1 John", "2 John",
    "3 John", "Jude", "Revelation",
]
_ORDER_INDEX = {book: i + 1 for i, book in enumerate(BOOK_ORDER)}


def _genre_for(order: int) -> str:
    """Map a book's canonical order (1-66, per BOOK_ORDER) to a genre bucket.
    Boundaries follow the standard Protestant-canon grouping (Pentateuch,
    historical, wisdom/poetry, major+minor prophets, gospels, epistles,
    apocalyptic) — Acts (order 44) is the one exception, classed as history
    despite sitting right after the gospels.
    """
    if order <= 5:
        return "law"
    if order <= 17 or order == 44:
        return "history"
    if order <= 22:
        return "poetry"
    if order <= 39:
        return "prophecy"
    if order <= 43:
        return "gospel"
    if order == 66:
        return "apocalyptic"
    return "epistle"


def _testament_for(order: int) -> str:
    """OT is the first 39 books in canonical order, NT the remaining 27."""
    return "OT" if order <= 39 else "NT"


def _batched(items: list, size: int):
    """Yield successive `size`-length slices of `items` — keeps each OpenAI
    embeddings call and each Supabase upsert to a bounded batch instead of one
    giant request for the whole translation (~31,000 verses).
    """
    for i in range(0, len(items), size):
        yield items[i : i + size]


# A batch is retried this many times, waiting longer each time, before the
# run gives up. Supabase sits behind Cloudflare, which answers a slow or
# dropped upsert with a 520 page; those are transient and a retry clears them.
MAX_ATTEMPTS = 5
RETRY_BASE_SECONDS = 5


def _short_error(err: Exception) -> str:
    """One readable line for an error whose message may be a whole HTML page
    (a Cloudflare 5xx), so a failure doesn't flood the terminal."""
    text = " ".join(str(err).split())
    if "<!DOCTYPE html" in text or "<html" in text:
        code = next((c for c in ("520", "521", "522", "523", "524", "502", "503", "504") if f"Error code {c}" in text or f"errorcode_{c}" in text), "5xx")
        return f"Supabase was unreachable through Cloudflare (HTTP {code})"
    return text[:300]


def _with_retries(label: str, fn):
    """Run `fn`, retrying transient failures with a growing pause."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as err:  # network and gateway errors vary by library
            if attempt == MAX_ATTEMPTS:
                raise SystemExit(
                    f"{label} failed {MAX_ATTEMPTS} times: {_short_error(err)}\n"
                    "Everything before it is saved. Run the same command again to resume."
                ) from err
            wait = RETRY_BASE_SECONDS * 2 ** (attempt - 1)
            print(f"  {label} failed ({_short_error(err)}), retrying in {wait}s")
            time.sleep(wait)


def _existing_keys(supabase, translation: str, *, embedded_only: bool) -> set[tuple[str, int, int]]:
    """(book, chapter, verse) for every verse of `translation` already stored,
    so a rerun after a failure skips them instead of paying to embed them
    again. With `embedded_only`, a stored verse that still lacks an embedding
    isn't counted, so it gets embedded this time. Read in pages because
    PostgREST caps each response at 1000 rows."""
    keys: set[tuple[str, int, int]] = set()
    page = 1000
    start = 0
    while True:
        def read_page():
            query = supabase.table("verses").select("book, chapter, verse").eq("translation", translation)
            if embedded_only:
                query = query.not_.is_("embedding", "null")
            return query.order("id").range(start, start + page - 1).execute().data

        rows = _with_retries("Reading what's already ingested", read_page)
        keys.update((r["book"], r["chapter"], r["verse"]) for r in rows)
        if len(rows) < page:
            return keys
        start += page


# Rows per upsert. An embedded row carries 512 floats, a few KB of JSON each,
# and large embedded batches are what tend to time out behind Cloudflare; a
# text-only row is a few hundred bytes, so those batches can be much bigger.
EMBEDDED_BATCH_SIZE = 100
TEXT_ONLY_BATCH_SIZE = 500


def verse_row(verse: dict, translation: str, embedding: list[float] | None = None) -> dict:
    """The `verses` row for one verse from the input file, with its book
    metadata attached. The embedding key is only present when there is one,
    so a text-only upsert never overwrites a stored embedding with null."""
    order = _ORDER_INDEX.get(verse["book"])
    if order is None:
        raise ValueError(f"Unknown book name: {verse['book']!r}, add it to BOOK_ORDER")
    row = {
        "translation": translation,
        "book": verse["book"],
        "book_order": order,
        "testament": _testament_for(order),
        "genre": _genre_for(order),
        "chapter": verse["chapter"],
        "verse": verse["verse"],
        "text": verse["text"],
    }
    if embedding is not None:
        row["embedding"] = embedding
    return row


def main() -> None:
    """CLI entry point: load the verse JSON, embed (search translation only)
    and upsert in batches, print progress. See the module docstring for the
    expected input file shape.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--translation", required=True)
    parser.add_argument(
        "--batch-size", type=int, default=None,
        help=f"rows per upsert (default {EMBEDDED_BATCH_SIZE} when embedding, {TEXT_ONLY_BATCH_SIZE} otherwise)",
    )
    parser.add_argument("--all", action="store_true", help="re-embed and upsert every verse, even ones already stored")
    args = parser.parse_args()

    embed = args.translation == settings.search_translation
    batch_size = args.batch_size or (EMBEDDED_BATCH_SIZE if embed else TEXT_ONLY_BATCH_SIZE)

    # An empty verse (some sources leave omitted verses blank) has nothing to
    # read or embed, and the embeddings API rejects empty input outright.
    raw_verses = [v for v in json.loads(args.file.read_text()) if v["text"].strip()]
    openai_client = OpenAI(api_key=settings.openai_api_key) if embed else None
    supabase = get_supabase()

    if not args.all:
        stored = _existing_keys(supabase, args.translation, embedded_only=embed)
        if stored:
            before = len(raw_verses)
            raw_verses = [v for v in raw_verses if (v["book"], v["chapter"], v["verse"]) not in stored]
            print(f"{before - len(raw_verses)} verses of {args.translation} already stored, skipping them (pass --all to redo)")

    total = len(raw_verses)
    if embed:
        print(f"Ingesting and embedding {total} verses ({args.translation}, the search translation) from {args.file}")
    else:
        print(
            f"Ingesting {total} verses ({args.translation}) from {args.file} as text only; "
            f"vector search borrows {settings.search_translation}'s embeddings"
        )

    for batch_num, batch in enumerate(_batched(raw_verses, batch_size), start=1):
        if embed:
            texts = [v["text"] for v in batch]
            embeddings = _with_retries(
                f"Embedding batch {batch_num}",
                lambda: openai_client.embeddings.create(
                    model=settings.embedding_model, input=texts, dimensions=settings.embedding_dim
                ).data,
            )
            rows = [verse_row(v, args.translation, e.embedding) for v, e in zip(batch, embeddings)]
        else:
            rows = [verse_row(v, args.translation) for v in batch]

        _with_retries(
            f"Saving batch {batch_num}",
            lambda: supabase.table("verses").upsert(rows, on_conflict="translation,book,chapter,verse").execute(),
        )
        done = min(batch_num * batch_size, total)
        print(f"  {done}/{total} {'embedded + ' if embed else ''}upserted")

    # The HNSW index (supabase/schema.sql) updates itself as rows arrive, so
    # there is nothing to rebuild afterwards.
    print("Done.")


if __name__ == "__main__":
    main()
