"""Answers to questions asked word for word before, kept for a day.

Most of all the welcome page's "Try" questions, which guests tap again and
again: a repeat replays the stream it produced the first time, costs no model
call and arrives at once. Only a study with no memories is kept, since
memories make an answer one person's own, and a prayer always is.

Held in this process only, so a restart starts it empty.
"""

import re
import time
from collections import OrderedDict
from threading import Lock

TTL_SECONDS = 24 * 60 * 60
MAX_ENTRIES = 256

_entries: OrderedDict[tuple[str, str], tuple[float, list[dict]]] = OrderedDict()
_lock = Lock()


def key(query: str, translation: str) -> tuple[str, str]:
    """Case, spacing and closing punctuation don't make a new question."""
    text = re.sub(r"\s+", " ", query).strip().lower().rstrip("?.! ")
    return translation.upper(), text


def get(cache_key: tuple[str, str]) -> list[dict] | None:
    with _lock:
        entry = _entries.get(cache_key)
        if not entry:
            return None
        stored_at, events = entry
        if time.monotonic() - stored_at > TTL_SECONDS:
            del _entries[cache_key]
            return None
        _entries.move_to_end(cache_key)
        return events


def put(cache_key: tuple[str, str], events: list[dict]) -> None:
    with _lock:
        _entries[cache_key] = (time.monotonic(), events)
        _entries.move_to_end(cache_key)
        while len(_entries) > MAX_ENTRIES:
            _entries.popitem(last=False)


def clear() -> None:
    with _lock:
        _entries.clear()
