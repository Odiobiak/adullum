"""Aquila's memory of the person she is talking with.

Two halves, both only for signed-in people who have memory switched on:
- `recall` runs before a turn: it embeds the question and pulls back the few
  notes most related to it, which main.py hands the graph as `memories`.
- `remember_turn` runs after the answer has already reached the person: one
  small LLM call decides whether the exchange said anything worth keeping
  about them (what they are studying, a season they are in, someone they are
  praying for), and stores it as a short note with its own embedding.

Everything here is non-fatal by design. Memory is a kindness layered on top
of a grounded answer, so a missing table, a failed embedding, or a slow LLM
call degrades to "Aquila doesn't remember this time", never to a failed turn.
Notes are never Scripture: synthesize and ground_check are told so explicitly
(see app/agent/nodes.py), so a memory can shape tone but never support a
claim about what the Bible says.
"""

import logging
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.config import settings
from app.db import get_supabase
from app.retrieval import embed_query

log = logging.getLogger(__name__)

_llm = ChatOpenAI(model=settings.chat_model, api_key=settings.openai_api_key, temperature=0)

RECALL_COUNT = 4
RECALL_MIN_SIMILARITY = 0.25
# Two notes this close are the same thing said twice ("studying Romans with
# my small group" vs. "doing Romans in small group"), so the second is dropped.
DUPLICATE_SIMILARITY = 0.9


def memory_enabled(user_id: str) -> bool:
    try:
        rows = (
            get_supabase().table("profiles").select("memory_enabled").eq("id", user_id).limit(1).execute().data
        )
    except Exception:
        return False
    # No profile row yet means the person has never turned memory off.
    return rows[0]["memory_enabled"] if rows else True


def recall(user_id: str, query: str) -> list[str]:
    if not memory_enabled(user_id):
        return []
    try:
        rows = (
            get_supabase()
            .rpc(
                "match_user_memories",
                {
                    "p_user_id": user_id,
                    "query_embedding": embed_query(query),
                    "match_count": RECALL_COUNT,
                    "min_similarity": RECALL_MIN_SIMILARITY,
                },
            )
            .execute()
            .data
        )
    except Exception:
        log.warning("memory recall failed", exc_info=True)
        return []
    return [_dated(r["content"], r["created_at"]) for r in rows]


def _dated(content: str, created_at: str) -> str:
    """Prefixes how long ago a note was kept, so Aquila can say "a few weeks
    ago you mentioned" instead of treating everything as said just now."""
    try:
        when = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return content
    days = (datetime.now(timezone.utc) - when).days
    if days < 1:
        ago = "earlier today"
    elif days < 14:
        ago = f"{days} day{'s' if days != 1 else ''} ago"
    elif days < 60:
        ago = f"about {days // 7} weeks ago"
    else:
        ago = f"about {days // 30} months ago"
    return f"({ago}) {content}"


class MemoryNotes(BaseModel):
    notes: list[str] = Field(
        description=(
            "Zero to two short notes about the PERSON (not about Scripture), each a "
            "single sentence in the third person. Empty when nothing personal was shared."
        )
    )


REMEMBER_SYSTEM_PROMPT = """You keep a small notebook for Aquila, a Bible study companion, \
so she can know the person she talks with over time the way a good friend would.

Read one exchange and write down only what is worth remembering about the person \
themselves for future conversations: what they are studying or reading, who they \
study with, a season of life they shared (a loss, a new job, a decision, waiting), \
someone they are praying for, a question they keep returning to, how they like to be \
answered.

Rules:
- Any detail they volunteer about their own life counts, even in passing inside a \
Bible question. Keep it.
- Write nothing when the question has no personal detail in it at all.

Examples:
- "I'm leading a small group through Romans this autumn. What does Romans 8:28 mean?" \
-> ["They are leading a small group through Romans this autumn."]
- "My dad passed last month. Where is God in grief?" -> ["They lost their dad last month."]
- "I start a new job Monday and I'm anxious. Any verses?" -> ["They start a new job soon \
and feel anxious about it."]
- "What does John 3:16 mean?" -> []
- "Who wrote Hebrews?" -> []
- Never record what the Bible says or what Aquila answered. Only the person.
- Each note is one plain sentence, third person ("They are studying Romans with their \
small group."). No names of third parties beyond a relationship ("their mother").
- Never use an em dash."""


def remember_turn(user_id: str, session_id: str | None, query: str, answer: str) -> None:
    if not memory_enabled(user_id):
        return
    try:
        result: MemoryNotes = _llm.with_structured_output(MemoryNotes).invoke(
            [
                SystemMessage(REMEMBER_SYSTEM_PROMPT),
                HumanMessage(f"They asked:\n{query}\n\nAquila answered:\n{answer[:2000]}"),
            ]
        )
    except Exception:
        log.warning("memory extraction failed", exc_info=True)
        return
    for note in result.notes[:2]:
        store_note(user_id, note.strip(), kind="note", session_id=session_id)


def store_note(
    user_id: str,
    content: str,
    *,
    kind: str = "note",
    session_id: str | None = None,
    journal_id: str | None = None,
    prayer_id: str | None = None,
) -> None:
    """Embed `content` and keep it as a note about the person, unless an
    almost identical note is already kept. A note made from a journal entry or
    a prayer carries that row's id, so it is deleted along with it."""
    if not content:
        return
    try:
        embedding = embed_query(content)
        db = get_supabase()
        dupes = (
            db.rpc(
                "match_user_memories",
                {
                    "p_user_id": user_id,
                    "query_embedding": embedding,
                    "match_count": 1,
                    "min_similarity": DUPLICATE_SIMILARITY,
                },
            )
            .execute()
            .data
        )
        if dupes and kind == "note":
            return
        row = {
            "user_id": user_id,
            "content": content,
            "kind": kind,
            "session_id": session_id,
            "journal_id": journal_id,
            "embedding": embedding,
        }
        # Only sent when set, so journal and conversation notes keep working on a
        # database where the prayers migration (which adds the column) hasn't run.
        if prayer_id:
            row["prayer_id"] = prayer_id
        db.table("user_memories").insert(row).execute()
    except Exception:
        log.warning("storing memory failed", exc_info=True)
