"""Load a public-domain translation into Supabase: attach book metadata, embed
in batches, upsert.

Expects a JSON file that is a flat list of verse objects:
    [{"book": "Genesis", "chapter": 1, "verse": 1, "text": "In the beginning..."}, ...]

Sources for public-domain translations (KJV, ASV, WEB, BSB) are widely available
as JSON/CSV, e.g. https://github.com/scrollmapper/bible_databases or
https://bereanbible.com/bsb.json — verify the license on whichever you pick
before ingesting; a project going on GitHub should not bundle a copyrighted
translation.

Usage:
    python scripts/ingest.py --file data/bsb.json --translation BSB
"""

import argparse
import json
import sys
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


def main() -> None:
    """CLI entry point: load the verse JSON, embed + upsert in batches, print
    progress. See the module docstring for the expected input file shape.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--translation", required=True)
    parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args()

    raw_verses = json.loads(args.file.read_text())
    openai_client = OpenAI(api_key=settings.openai_api_key)
    supabase = get_supabase()

    total = len(raw_verses)
    print(f"Ingesting {total} verses ({args.translation}) from {args.file}")

    for batch_num, batch in enumerate(_batched(raw_verses, args.batch_size), start=1):
        texts = [v["text"] for v in batch]
        embeddings = openai_client.embeddings.create(
            model=settings.embedding_model, input=texts
        ).data

        rows = []
        for verse, embedding in zip(batch, embeddings):
            order = _ORDER_INDEX.get(verse["book"])
            if order is None:
                raise ValueError(f"Unknown book name: {verse['book']!r} — add it to BOOK_ORDER")
            rows.append(
                {
                    "translation": args.translation,
                    "book": verse["book"],
                    "book_order": order,
                    "testament": _testament_for(order),
                    "genre": _genre_for(order),
                    "chapter": verse["chapter"],
                    "verse": verse["verse"],
                    "text": verse["text"],
                    "embedding": embedding.embedding,
                }
            )

        supabase.table("verses").upsert(rows, on_conflict="translation,book,chapter,verse").execute()
        done = min(batch_num * args.batch_size, total)
        print(f"  {done}/{total} embedded + upserted")

    print("Done. Now build the vector index in Supabase SQL editor:")
    print(
        "  reindex or run: create index if not exists verses_embedding_idx on verses "
        "using ivfflat (embedding vector_cosine_ops) with (lists = 100);"
    )


if __name__ == "__main__":
    main()
