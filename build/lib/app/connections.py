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

Each seed also gets its best-voted classic cross-references (the
cross_references table, loaded by scripts/ingest_cross_references.py from
OpenBible.info's CC BY data built on the Treasury of Scripture Knowledge).
Every edge says which kind of link it is in `kinds`: "meaning", "cross_ref",
or both. Until that table exists the graph simply shows meaning alone.

POST /connections/explain asks Aquila why two linked passages connect
(app/agent/nodes.py::explain_link), cached so a link is only explained once.
"""

import json
import logging
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from postgrest.exceptions import APIError
from pydantic import BaseModel, Field

from app.agent.nodes import explain_link
from app.config import settings
from app.db import get_supabase
from app.plan import BOOK_CHAPTER_COUNTS
from app.retrieval import lookup_by_reference, parse_reference

log = logging.getLogger(__name__)

router = APIRouter()

_BOOK_ORDER = {book: i + 1 for i, book in enumerate(BOOK_CHAPTER_COUNTS)}
MAX_SEEDS = 6
CROSS_REFS_PER_SEED = 5
MAX_EXPLAIN_VERSES = 4  # a passage sent to explain is cut to its first few verses


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


def cross_ref_label(row: dict) -> str:
    """The passage a cross-reference points to: "Proverbs 8:22-30"."""
    start, end = row["to_verse_start"], row["to_verse_end"]
    span = f"{start}" if start == end else f"{start}-{end}"
    return f"{row['to_book']} {row['to_chapter']}:{span}"


def _cross_references(seed: dict, limit: int) -> list[dict]:
    """A verse's best-voted classic cross-references. Empty, not an error,
    before the cross-references migration has run."""
    try:
        return (
            get_supabase()
            .table("cross_references")
            .select("to_book, to_chapter, to_verse_start, to_verse_end, votes")
            .eq("from_book", seed["book"])
            .eq("from_chapter", seed["chapter"])
            .eq("from_verse", seed["verse"])
            .order("votes", desc=True)
            .limit(limit)
            .execute()
            .data
        )
    except APIError as err:
        if err.code not in ("42P01", "PGRST205"):
            log.warning("cross-reference lookup failed", exc_info=True)
        return []


def add_edge(edges: dict, source: str, target: str, kind: str, **extra) -> None:
    """Record a link between two nodes, merging with one already there: the
    same pair can be both a cross-reference and close in meaning."""
    key = tuple(sorted((source, target)))
    edge = edges.setdefault(key, {"source": source, "target": target, "weight": None, "kinds": []})
    if kind not in edge["kinds"]:
        edge["kinds"].append(kind)
    weight = extra.pop("weight", None)
    if weight is not None and (edge["weight"] is None or edge["weight"] < weight):
        edge["weight"] = weight
    edge.update(extra)


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

            # Classic cross-references, best-voted first. A link to a run of
            # verses is drawn to its first verse and labelled with the run.
            for xref in _cross_references(seed, CROSS_REFS_PER_SEED):
                rows = _verse_range_rows(
                    xref["to_book"], xref["to_chapter"], xref["to_verse_start"], xref["to_verse_start"],
                    translation, "book, chapter, verse, text",
                )
                if not rows:
                    continue  # a verse this translation doesn't have
                node = nodes.setdefault(_ref(rows[0]["book"], rows[0]["chapter"], rows[0]["verse"]), _node(rows[0], seed=False))
                add_edge(edges, seed_node["id"], node["id"], "cross_ref", votes=xref["votes"], passage=cross_ref_label(xref))

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
                node = nodes.setdefault(_ref(n["book"], n["chapter"], n["verse"]), _node(n, seed=False))
                add_edge(edges, seed_node["id"], node["id"], "meaning", weight=round(float(n["similarity"]), 4))
                kept += 1
                if kept >= k:
                    break

    if not nodes:
        raise HTTPException(status_code=404, detail="None of those references were found.")
    return {"translation": translation, "nodes": list(nodes.values()), "edges": list(edges.values())}


# ---------------------------------------------------------------------------
# "Why are these connected?"
# ---------------------------------------------------------------------------
class ExplainIn(BaseModel):
    a: str = Field(max_length=40, description="One end of the link, e.g. 'John 3:16'")
    b: str = Field(max_length=40, description="The other end, e.g. 'Romans 5:8'")
    translation: str | None = Field(default=None, max_length=12)
    kinds: list[Literal["meaning", "cross_ref"]] = Field(default_factory=list, max_length=2)


def _passage(ref_text: str, translation: str):
    parsed = parse_reference(ref_text)
    verses = lookup_by_reference(parsed, translation)[:MAX_EXPLAIN_VERSES] if parsed and parsed.verse_start else []
    if not verses:
        raise HTTPException(status_code=404, detail=f"Couldn't find {ref_text}.")
    return verses


@lru_cache(maxsize=512)
def _explained(a: str, b: str, translation: str, cross_ref: bool, close_in_meaning: bool) -> str:
    """Cached by the exact link, so tapping the same line twice, or two people
    tapping it, costs one model call. Errors aren't cached."""
    return explain_link(
        _passage(a, translation), _passage(b, translation), cross_ref=cross_ref, close_in_meaning=close_in_meaning
    )


@router.post("/connections/explain")
def explain(body: ExplainIn) -> dict:
    """Aquila's two or three sentences on how two linked passages connect,
    using only those two passages."""
    translation = (body.translation or settings.default_translation).upper()
    text = _explained(body.a.strip(), body.b.strip(), translation, "cross_ref" in body.kinds, "meaning" in body.kinds)
    return {"a": body.a, "b": body.b, "translation": translation, "explanation": text}
