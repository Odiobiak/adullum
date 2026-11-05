"""The visual knowledge graph: how a passage connects across Scripture.

GET /connections takes one or more references and returns nodes and edges
for web/graph.js to lay out. Each seed verse's stored embedding is fed back
through the existing `match_verses` RPC to find the verses nearest to it in
meaning, anywhere in the canon. Only the search translation stores
embeddings, so a seed's embedding is read from that translation's copy of the
verse, whichever translation the graph is showing. That needs no new SQL and no LLM call,
and it reuses the exact similarity measure retrieval already trusts, so the
graph shows the same neighbourhood Aquila sees when she answers.

Verses from the seed's own chapter are left out: they're near in meaning
simply because they're near on the page, and the interesting part of a
cross-reference map is the jump to another book.
"""

import json

from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.db import get_supabase
from app.plan import BOOK_CHAPTER_COUNTS
from app.retrieval import parse_reference

router = APIRouter()

_BOOK_ORDER = {book: i + 1 for i, book in enumerate(BOOK_CHAPTER_COUNTS)}
MAX_SEEDS = 6


def book_meta(book: str) -> dict:
    """Same buckets as scripts/ingest.py::_genre_for, so a node's colour
    matches the `genre` column stored on the verse row."""
    order = _BOOK_ORDER.get(book, 0)
    if order <= 5:
        genre = "law"
    elif order <= 17 or order == 44:
        genre = "history"
    elif order <= 22:
        genre = "poetry"
    elif order <= 39:
        genre = "prophecy"
    elif order <= 43:
        genre = "gospel"
    elif order == 66:
        genre = "apocalyptic"
    else:
        genre = "epistle"
    return {"order": order, "testament": "OT" if order <= 39 else "NT", "genre": genre}


def _ref(book: str, chapter: int, verse: int) -> str:
    return f"{book} {chapter}:{verse}"


def _node(row: dict, *, seed: bool) -> dict:
    return {
        "id": _ref(row["book"], row["chapter"], row["verse"]),
        "book": row["book"],
        "chapter": row["chapter"],
        "verse": row["verse"],
        "text": row["text"],
        "seed": seed,
        **book_meta(row["book"]),
    }


def _verse_range_rows(book: str, chapter: int, start: int, end: int, translation: str, columns: str) -> list[dict]:
    """`columns` for verses `start`..`end` of one chapter in one translation."""
    return (
        get_supabase()
        .table("verses")
        .select(columns)
        .eq("translation", translation)
        .eq("book", book)
        .eq("chapter", chapter)
        .gte("verse", start)
        .lte("verse", end)
        .order("verse")
        .execute()
        .data
    )


def _seed_rows(ref_text: str, translation: str) -> list[dict]:
    """The seed verses for one reference, in `translation`, each with the
    `embedding` of the same verse in the search translation (None if that
    translation doesn't have the verse)."""
    parsed = parse_reference(ref_text)
    if not parsed:
        return []
    # A whole-chapter reference seeds from its opening verse only, so one
    # seed never fans out into a chapter's worth of nodes.
    start = parsed.verse_start or 1
    end = parsed.verse_end or start
    end = min(end, start + 2)  # a long range seeds from its first three verses

    seeds = _verse_range_rows(parsed.book, parsed.chapter, start, end, translation, "book, chapter, verse, text")
    embedded = _verse_range_rows(
        parsed.book, parsed.chapter, start, end, settings.search_translation, "verse, embedding"
    )
    embedding_by_verse = {row["verse"]: row["embedding"] for row in embedded}
    return [{**seed, "embedding": embedding_by_verse.get(seed["verse"])} for seed in seeds]


def _embedding(raw) -> list[float]:
    # PostgREST returns a pgvector column (halfvec included) as its text form,
    # "[0.1,0.2,...]".
    return json.loads(raw) if isinstance(raw, str) else raw


@router.get("/verse")
def get_verse(ref: str, translation: str | None = None) -> dict:
    """Plain verse text for a reference, for the graph's side panel and for
    saving a single verse to the journal."""
    translation = translation or settings.default_translation
    parsed = parse_reference(ref)
    if not parsed:
        raise HTTPException(status_code=400, detail="That doesn't look like a Bible reference.")
    q = (
        get_supabase()
        .table("verses")
        .select("book, chapter, verse, text")
        .eq("translation", translation)
        .eq("book", parsed.book)
        .eq("chapter", parsed.chapter)
    )
    if parsed.verse_start is not None:
        q = q.gte("verse", parsed.verse_start).lte("verse", parsed.verse_end)
    rows = q.order("verse").limit(40).execute().data
    if not rows:
        raise HTTPException(status_code=404, detail="Verse not found")
    return {"ref": ref, "translation": translation, "verses": rows, **book_meta(parsed.book)}


@router.get("/connections")
def connections(
    refs: str = Query(description="One or more references separated by ';', e.g. 'John 3:16;Romans 8:28'"),
    translation: str | None = None,
    k: int = Query(default=6, ge=1, le=12),
) -> dict:
    translation = translation or settings.default_translation
    ref_list = [r.strip() for r in refs.split(";") if r.strip()][:MAX_SEEDS]
    if not ref_list:
        raise HTTPException(status_code=400, detail="Give at least one reference.")

    nodes: dict[str, dict] = {}
    edges: dict[tuple[str, str], dict] = {}
    db = get_supabase()

    for ref_text in ref_list:
        for seed in _seed_rows(ref_text, translation):
            seed_node = _node(seed, seed=True)
            nodes[seed_node["id"]] = seed_node
            if not seed.get("embedding"):
                continue
            neighbours = (
                db.rpc(
                    "match_verses",
                    {
                        "query_embedding": _embedding(seed["embedding"]),
                        "match_translation": translation,
                        # Over-fetch: same-chapter hits are filtered out below.
                        "match_count": k + 12,
                    },
                )
                .execute()
                .data
            )
            kept = 0
            for n in neighbours:
                if n["book"] == seed["book"] and n["chapter"] == seed["chapter"]:
                    continue
                node = _node(n, seed=False)
                existing = nodes.get(node["id"])
                if existing is None:
                    nodes[node["id"]] = node
                key = tuple(sorted((seed_node["id"], node["id"])))
                weight = round(float(n["similarity"]), 4)
                if key not in edges or edges[key]["weight"] < weight:
                    edges[key] = {"source": seed_node["id"], "target": node["id"], "weight": weight}
                kept += 1
                if kept >= k:
                    break

    if not nodes:
        raise HTTPException(status_code=404, detail="None of those references were found.")
    return {"translation": translation, "nodes": list(nodes.values()), "edges": list(edges.values())}
