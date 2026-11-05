"""Download a public-domain translation and write it in the flat shape
scripts/ingest.py reads:

    [{"book": "Genesis", "chapter": 1, "verse": 1, "text": "In the beginning..."}, ...]

Usage:
    python scripts/fetch_translation.py --translation KJV     # writes data/kjv.json
    python scripts/ingest.py --file data/kjv.json --translation KJV

Both sources nest the text as books -> chapters -> verses, and each needs a
little tidying on the way through:
- book names come as "I Samuel" or "Revelation of John" and are mapped to the
  canonical names the rest of the app uses (app/plan.py::BOOK_CHAPTER_COUNTS);
- WEB pads many verses with stray spaces, collapsed here;
- ASV opens a bracket before "Selah" and never closes it;
- WEB runs the Song of Solomon's speaker headings ("Beloved", "Lover",
  "Friends") onto the end of the verse before them, so they are cut off;
- ASV leaves verses its translators judged not original (Matthew 17:21 and
  others) as empty strings, which are dropped rather than ingested, since an
  empty verse has nothing to embed or to read.

The licence on each source is noted next to it. Only add a translation here
if it is genuinely in the public domain (see CLAUDE.md, "Product constraints").
"""

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.plan import BOOK_CHAPTER_COUNTS  # noqa: E402
from app.retrieval import canonical_book  # noqa: E402

SOURCES = {
    # scrollmapper/bible_databases, public domain texts.
    "KJV": "https://raw.githubusercontent.com/scrollmapper/bible_databases/master/formats/json/KJV.json",
    "ASV": "https://raw.githubusercontent.com/scrollmapper/bible_databases/master/formats/json/ASV.json",
    # getbible.net, which lists the WEB's licence as Public Domain.
    "WEB": "https://api.getbible.net/v2/web.json",
    # BSB has been public domain since 2023. bsb.json from bereanbible.com is
    # already flat; this copy exists so every translation can come from here.
    "BSB": "https://raw.githubusercontent.com/scrollmapper/bible_databases/master/formats/json/BSB.json",
}

_ROMAN = {"I": "1", "II": "2", "III": "3"}
# Only ever after the verse's closing punctuation, and only in this one book.
_SONG_SPEAKER_RE = re.compile(r"(?<=[.!?\u201d\u2019])\s+(?:Beloved|Lover|Friends)$")
_SPECIAL = {"revelationofjohn": "Revelation"}


def normalize_book(name: str) -> str:
    """Map a source's book name to the canonical one, or raise."""
    parts = name.strip().split(" ", 1)
    if len(parts) == 2 and parts[0] in _ROMAN:
        name = f"{_ROMAN[parts[0]]} {parts[1]}"
    key = re.sub(r"[\s.]", "", name).lower()
    canonical = _SPECIAL.get(key) or canonical_book(name)
    if not canonical:
        raise ValueError(f"Unknown book name in source: {name!r}")
    return canonical


def clean_text(text: str, book: str = "") -> str:
    text = re.sub(r"\[Selah\]?", "Selah", text)
    text = re.sub(r"\s+", " ", text).strip()
    if book == "Song of Solomon":
        text = _SONG_SPEAKER_RE.sub("", text)
    return text


def flatten(source: dict) -> list[dict]:
    """Nested source JSON to the flat ingest list, in canonical book order."""
    out: list[dict] = []
    seen_books: set[str] = set()
    for book in source["books"]:
        name = normalize_book(book["name"])
        if name in seen_books:
            raise ValueError(f"{name} appears twice in the source")
        seen_books.add(name)
        for chapter in book["chapters"]:
            number = int(chapter["chapter"])
            for verse in chapter["verses"]:
                text = clean_text(verse.get("text") or "", name)
                if text:
                    out.append({"book": name, "chapter": number, "verse": int(verse["verse"]), "text": text})
    missing = [b for b in BOOK_CHAPTER_COUNTS if b not in seen_books]
    if missing:
        raise ValueError(f"Source is missing books: {', '.join(missing)}")
    order = {b: i for i, b in enumerate(BOOK_CHAPTER_COUNTS)}
    out.sort(key=lambda v: (order[v["book"]], v["chapter"], v["verse"]))
    return out


def check_chapters(verses: list[dict]) -> None:
    """Every book has exactly the chapter count the reader expects."""
    chapters: dict[str, set[int]] = {}
    for v in verses:
        chapters.setdefault(v["book"], set()).add(v["chapter"])
    for book, count in BOOK_CHAPTER_COUNTS.items():
        if chapters.get(book) != set(range(1, count + 1)):
            raise ValueError(f"{book} should have chapters 1-{count}, the source has {sorted(chapters.get(book, []))}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--translation", required=True, choices=sorted(SOURCES))
    parser.add_argument("--out", type=Path, help="defaults to data/<translation>.json")
    args = parser.parse_args()

    out = args.out or Path(__file__).resolve().parent.parent / "data" / f"{args.translation.lower()}.json"
    url = SOURCES[args.translation]
    print(f"Downloading {args.translation} from {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "adullum-fetch-translation"})
    with urllib.request.urlopen(request, timeout=120) as resp:
        source = json.load(resp)

    verses = flatten(source)
    check_chapters(verses)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(verses, ensure_ascii=False))
    print(f"Wrote {len(verses)} verses to {out}")
    print(f"Next: python scripts/ingest.py --file {out} --translation {args.translation}")


if __name__ == "__main__":
    main()
