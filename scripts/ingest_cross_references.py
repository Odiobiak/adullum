"""Load the classic cross-references that Connections draws alongside the
links found by meaning (app/connections.py).

The data is OpenBible.info's cross-references, licensed CC BY (the graph
credits it in its legend): the public-domain Treasury of Scripture Knowledge,
with readers' votes on how useful each link is. Run the migration
supabase/migrations/20261111_cross_references.sql first, then:

    python scripts/ingest_cross_references.py                 # downloads if needed
    python scripts/ingest_cross_references.py --min-votes 10  # a smaller set

Safe to re-run: rows already loaded are skipped, so a run that stops part way
can simply be started again.
"""

import argparse
import io
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_supabase  # noqa: E402
from app.plan import BOOK_CHAPTER_COUNTS  # noqa: E402

SOURCE_URL = "https://a.openbible.info/data/cross-references.zip"
DEFAULT_FILE = Path(__file__).resolve().parent.parent / "data" / "cross_references.txt"
DEFAULT_MIN_VOTES = 5  # keeps about 118,000 of the 344,000 links: the ones readers found useful
BATCH_SIZE = 1000
RETRIES = 3

# OpenBible's book codes (OSIS) -> the app's canonical book names, in canon order.
OSIS_BOOKS = dict(zip(
    [
        "Gen", "Exod", "Lev", "Num", "Deut", "Josh", "Judg", "Ruth", "1Sam", "2Sam",
        "1Kgs", "2Kgs", "1Chr", "2Chr", "Ezra", "Neh", "Esth", "Job", "Ps", "Prov",
        "Eccl", "Song", "Isa", "Jer", "Lam", "Ezek", "Dan", "Hos", "Joel", "Amos",
        "Obad", "Jonah", "Mic", "Nah", "Hab", "Zeph", "Hag", "Zech", "Mal",
        "Matt", "Mark", "Luke", "John", "Acts", "Rom", "1Cor", "2Cor", "Gal", "Eph",
        "Phil", "Col", "1Thess", "2Thess", "1Tim", "2Tim", "Titus", "Phlm", "Heb", "Jas",
        "1Pet", "2Pet", "1John", "2John", "3John", "Jude", "Rev",
    ],
    BOOK_CHAPTER_COUNTS,  # the same 66 books, in the same order
))


def parse_osis(ref: str) -> tuple[str, int, int] | None:
    """"1Cor.8.6" -> ("1 Corinthians", 8, 6), or None if it doesn't parse."""
    parts = ref.split(".")
    if len(parts) != 3 or parts[0] not in OSIS_BOOKS:
        return None
    try:
        return OSIS_BOOKS[parts[0]], int(parts[1]), int(parts[2])
    except ValueError:
        return None


def parse_line(line: str, min_votes: int) -> dict | None:
    """One line of the data file as a row, or None when it's the header, has
    too few votes, or doesn't parse. A target range that runs into the next
    chapter is kept as its first verse alone."""
    fields = line.rstrip("\n").split("\t")
    if len(fields) < 3:
        return None
    try:
        votes = int(fields[2])
    except ValueError:
        return None  # the header line
    if votes < min_votes:
        return None
    source = parse_osis(fields[0])
    start_ref, _, end_ref = fields[1].partition("-")
    start = parse_osis(start_ref)
    if not source or not start:
        return None
    end = parse_osis(end_ref) if end_ref else start
    same_chapter = end and end[:2] == start[:2] and end[2] >= start[2]
    return {
        "from_book": source[0], "from_chapter": source[1], "from_verse": source[2],
        "to_book": start[0], "to_chapter": start[1], "to_verse_start": start[2],
        "to_verse_end": end[2] if same_chapter else start[2],
        "votes": votes,
    }


def read_rows(path: Path, min_votes: int) -> list[dict]:
    rows = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            row = parse_line(line, min_votes)
            if row:
                key = (row["from_book"], row["from_chapter"], row["from_verse"], row["to_book"], row["to_chapter"], row["to_verse_start"])
                rows[key] = row  # the data has a handful of exact repeats; keep one
    return list(rows.values())


def download(path: Path) -> None:
    print(f"Downloading {SOURCE_URL} ...")
    with urllib.request.urlopen(SOURCE_URL, timeout=120) as resp:
        archive = zipfile.ZipFile(io.BytesIO(resp.read()))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(archive.read("cross_references.txt"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Load cross-references into Supabase.")
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    parser.add_argument("--min-votes", type=int, default=DEFAULT_MIN_VOTES)
    args = parser.parse_args()

    if not args.file.exists():
        download(args.file)
    rows = read_rows(args.file, args.min_votes)
    print(f"{len(rows):,} cross-references with at least {args.min_votes} votes.")

    table = get_supabase().table("cross_references")
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        for attempt in range(1, RETRIES + 1):
            try:
                table.upsert(batch, on_conflict="from_book,from_chapter,from_verse,to_book,to_chapter,to_verse_start", ignore_duplicates=True).execute()
                break
            except Exception as err:
                if attempt == RETRIES:
                    print(f"Stopped at row {i:,}: {err}. Run again to pick up from here.")
                    return 1
                time.sleep(2 * attempt)
        done = min(i + BATCH_SIZE, len(rows))
        if done % 20000 < BATCH_SIZE or done == len(rows):
            print(f"  {done:,} / {len(rows):,}")
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
