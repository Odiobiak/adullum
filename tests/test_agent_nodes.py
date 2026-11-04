"""Node-level unit tests that don't need a live LLM or Supabase: the pure
routing/formatting logic in app/agent/graph.py and the two format_citations/
retrieve node functions in app/agent/nodes.py that don't call an LLM.
"""

from langgraph.graph import END

from app.agent import nodes
from app.agent.graph import _after_citations, _after_classify, _after_ground_check
from app.agent.nodes import MAX_RETRIES, format_citations
from app.config import settings
from app.schemas import Verse


def make_verse(book: str, chapter: int, verse: int, text: str = "...") -> Verse:
    return Verse(book=book, chapter=chapter, verse=verse, text=text, translation="BSB")


class TestAfterClassify:
    def test_meta_intent_routes_to_answer_meta(self):
        assert _after_classify({"intent": "meta"}) == "answer_meta"

    def test_other_intents_route_to_retrieve(self):
        assert _after_classify({"intent": "thematic"}) == "retrieve"


class TestAfterGroundCheck:
    def test_grounded_moves_on(self):
        assert _after_ground_check({"grounded": True, "retries": 1}) == "format_citations"

    def test_ungrounded_within_budget_retries_again(self):
        assert _after_ground_check({"grounded": False, "retries": MAX_RETRIES}) == "retrieve"

    def test_ungrounded_past_budget_gives_up(self):
        assert (
            _after_ground_check({"grounded": False, "retries": MAX_RETRIES + 1})
            == "format_citations"
        )


class TestAfterCitations:
    def test_want_followups_routes_to_suggest_followups(self):
        assert _after_citations({"want_followups": True}) == "suggest_followups"

    def test_default_skips_followups(self):
        assert _after_citations({"want_followups": False}) == END
        assert _after_citations({}) == END


class TestFormatCitations:
    def test_keeps_only_the_verses_the_answer_actually_cites(self):
        cited = make_verse("John", 3, 16)
        uncited = make_verse("Romans", 8, 28)
        state = {"answer": "The promise is in (John 3:16).", "verses": [cited, uncited]}
        assert format_citations(state)["citations"] == [cited]

    def test_falls_back_to_full_verse_list_when_nothing_matches(self):
        # A non-empty answer must never come back with zero citations, so an
        # answer that (correctly) says the verses don't address the question
        # still surfaces the verses it was given rather than an empty list.
        verses = [make_verse("John", 3, 16)]
        state = {"answer": "These verses don't address that question.", "verses": verses}
        assert format_citations(state)["citations"] == verses


class TestRetrieve:
    def test_widens_k_on_retry(self, monkeypatch):
        seen_k = []
        monkeypatch.setattr(
            nodes, "hybrid_retrieve", lambda query, translation, k=8: seen_k.append(k) or []
        )
        nodes.retrieve({"query": "q", "translation": "BSB", "retries": 0})
        nodes.retrieve({"query": "q", "translation": "BSB", "retries": 1})
        assert seen_k == [8, 14]

    def test_defaults_translation_when_caller_omits_it(self, monkeypatch):
        monkeypatch.setattr(nodes, "hybrid_retrieve", lambda query, translation, k=8: [])
        result = nodes.retrieve({"query": "q"})
        assert result["translation"] == settings.default_translation
