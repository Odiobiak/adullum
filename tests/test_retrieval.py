"""app/retrieval.py's two regex parsers decide which of the three retrieval
paths a query takes, so a wrong parse silently sends a question down the
wrong path rather than raising anywhere — exactly the kind of bug a test
catches and a code read doesn't.
"""

from app.retrieval import parse_book_mention, parse_reference


class TestParseReference:
    def test_plain_reference(self):
        ref = parse_reference("What does John 3:16 say?")
        assert ref.book == "John"
        assert ref.chapter == 3
        assert ref.verse_start == 16
        assert ref.verse_end == 16

    def test_alias_and_case_insensitive(self):
        ref = parse_reference("what does jn 3:16 mean")
        assert ref.book == "John"
        assert ref.chapter == 3

    def test_verse_range(self):
        ref = parse_reference("Romans 8:28-30")
        assert (ref.verse_start, ref.verse_end) == (28, 30)

    def test_numbered_book_alias(self):
        ref = parse_reference("1 cor 13:4")
        assert ref.book == "1 Corinthians"
        assert ref.chapter == 13

    def test_chapter_only_no_verse(self):
        ref = parse_reference("what happens in genesis 1")
        assert ref.book == "Genesis"
        assert ref.chapter == 1
        assert ref.verse_start is None
        # verse_end mirrors verse_start (both None) when no verse was given,
        # so a chapter-only reference still resolves to "whole chapter".
        assert ref.verse_end is None

    def test_no_book_name_falls_through(self):
        # Matches the regex's chapter-number shape but no recognizable book,
        # so this must return None and let vector/keyword search handle it.
        assert parse_reference("chapter 3 of that book") is None

    def test_no_reference_shape_at_all(self):
        assert parse_reference("What does propitiation mean?") is None


class TestParseBookMention:
    def test_book_of_phrasing(self):
        assert parse_book_mention("book of James") == "James"

    def test_book_of_embedded_in_sentence(self):
        assert (
            parse_book_mention("Give me a starting point for studying the book of James")
            == "James"
        )

    def test_numbered_book(self):
        assert parse_book_mention("book of 1 Corinthians") == "1 Corinthians"

    def test_bare_book_name_is_not_a_match(self):
        # Job, Mark, Acts, Titus, James, John, Ruth are also common English
        # words/names — parse_book_mention must only fire on the explicit
        # "book of X" phrasing, never a bare name, or these false-positive.
        assert parse_book_mention("Mark my words") is None
        assert parse_book_mention("Tell me about acts of kindness") is None

    def test_unresolvable_book_name_returns_none(self):
        assert parse_book_mention("book of Frodo") is None


class TestHybridRetrieveFallback:
    """A statement timeout in `match_verses` once took down every answer, with
    the stream ending silently after classify_intent. Vector search failing
    should cost recall, not the whole response.
    """

    def test_keyword_results_survive_a_vector_search_timeout(self, monkeypatch):
        from postgrest.exceptions import APIError

        from app import retrieval
        from app.schemas import Verse

        def timed_out(query, translation, k=8):
            raise APIError({"message": "canceling statement due to statement timeout", "code": "57014"})

        keyword_hit = Verse(
            book="Romans", chapter=3, verse=25, text="...", translation="KJV", source="keyword"
        )
        monkeypatch.setattr(retrieval, "vector_search", timed_out)
        monkeypatch.setattr(retrieval, "keyword_search", lambda query, translation, k=8: [keyword_hit])

        assert retrieval.hybrid_retrieve("what does propitiation mean", "KJV") == [keyword_hit]
