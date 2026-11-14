"""The Church tab's pure parts: safe links, reading pages and feeds, merging a
church draft, notices, the week after a sermon, and sermon notes drafted from
a link. Nothing here touches the network, the database or a model."""

import threading
import time
from datetime import date

import pytest

from app import church_web as web
from app.churches import (
    ChurchDraft,
    ChurchIn,
    SermonDraft,
    _DraftEvent,
    _DraftGathering,
    _Point,
    _Quote,
    carry_notice_dates,
    clean_time,
    day_index,
    merge_draft,
    note_from_draft,
    unseen_notices,
    week_steps,
)


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------
def test_normalise_url_adds_https():
    assert web.normalise_url("harvest.org") == "https://harvest.org"
    assert web.normalise_url(" http://a.org/x ") == "http://a.org/x"


@pytest.mark.parametrize("url", ["http://localhost:8000", "http://127.0.0.1/", "http://10.0.0.5/", "http://169.254.169.254/latest", "ftp://example.com", "https://user:pw@example.com"])
def test_check_url_refuses_private_and_odd_links(url):
    with pytest.raises(web.FetchError):
        web.check_url(url)


def test_church_links_must_be_web_links():
    church = ChurchIn(name="Hope Street", website="hopestreet.org", time_zone="Europe/London")
    assert church.website == "https://hopestreet.org"
    with pytest.raises(ValueError):
        ChurchIn(name="Hope Street", time_zone="Mars/Olympus")


@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=4t4AQ15yj1M", "4t4AQ15yj1M"),
    ("https://youtu.be/4t4AQ15yj1M?t=30", "4t4AQ15yj1M"),
    ("youtube.com/live/4t4AQ15yj1M", "4t4AQ15yj1M"),
    ("https://www.youtube.com/@church", None),
    ("https://vimeo.com/12345", None),
])
def test_youtube_video_id(url, expected):
    assert web.youtube_video_id(url) == expected


# ---------------------------------------------------------------------------
# YouTube pages and feeds
# ---------------------------------------------------------------------------
def test_live_needs_both_the_flag_and_a_watch_page():
    live = '<link rel="canonical" href="https://www.youtube.com/watch?v=4t4AQ15yj1M"> "isLiveNow":true'
    assert web.youtube_live_video(live) == "4t4AQ15yj1M"
    assert web.youtube_live_video(live.replace("true", "false")) is None
    assert web.youtube_live_video('"isLiveNow":true <link rel="canonical" href="https://www.youtube.com/channel/UCSJ4gkVC6NrvII8umztf0Ow">') is None


def test_channel_id_from_a_channel_page():
    html = '<link rel="canonical" href="https://www.youtube.com/channel/UCSJ4gkVC6NrvII8umztf0Ow">'
    assert web.youtube_channel_id(html) == "UCSJ4gkVC6NrvII8umztf0Ow"
    assert web.youtube_channel_id('"externalId":"UCSJ4gkVC6NrvII8umztf0Ow"') == "UCSJ4gkVC6NrvII8umztf0Ow"
    assert web.youtube_channel_id("<html></html>") is None


FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
 <entry>
  <yt:videoId>aaaaaaaaaaa</yt:videoId><title>Short clip</title>
  <link rel="alternate" href="https://www.youtube.com/shorts/aaaaaaaaaaa"/><published>2026-11-05T10:00:00+00:00</published>
 </entry>
 <entry>
  <yt:videoId>bbbbbbbbbbb</yt:videoId><title>Strength for the weary | Isaiah 40</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=bbbbbbbbbbb"/><published>2026-11-01T10:00:00+00:00</published>
  <media:group><media:description>Pastor Tunde on Isaiah 40:28-31.</media:description></media:group>
 </entry>
</feed>"""


def test_youtube_feed_skips_shorts():
    videos = web.parse_youtube_feed(FEED)
    assert [v["video_id"] for v in videos] == ["bbbbbbbbbbb"]
    assert videos[0]["published"] == "2026-11-01"
    assert videos[0]["url"] == "https://www.youtube.com/watch?v=bbbbbbbbbbb"
    assert "Isaiah 40:28-31" in videos[0]["description"]


def test_podcast_feed_ids_are_stable():
    xml = """<rss><channel><item><title>Faith that waits</title><guid>ep-12</guid>
    <enclosure url="https://cdn.example.com/12.mp3"/><description>&lt;p&gt;On Habakkuk 2&lt;/p&gt;</description></item></channel></rss>"""
    first, again = web.parse_podcast_feed(xml), web.parse_podcast_feed(xml)
    assert first[0]["id"] == again[0]["id"] and first[0]["id"].startswith("pod:")
    assert first[0]["audio_url"] == "https://cdn.example.com/12.mp3"
    assert "Habakkuk 2" in first[0]["description"] and "<p>" not in first[0]["description"]


def test_podcast_feed_cut_off_part_way_keeps_the_whole_episodes():
    item = '<item><title>Ep {n}</title><guid>ep-{n}</guid><enclosure url="https://cdn.example.com/{n}.mp3"/></item>'
    xml = '<?xml version="1.0" encoding="UTF-8"?><rss><channel>' + "".join(item.format(n=n) for n in range(5))
    cut = xml[: xml.index("<item><title>Ep 4") + 20]  # stopped reading inside the fifth
    assert [e["title"] for e in web.parse_podcast_feed(cut)] == ["Ep 0", "Ep 1", "Ep 2", "Ep 3"]
    assert [e["title"] for e in web.parse_podcast_feed(xml, limit=2)] == ["Ep 0", "Ep 1"]


def test_an_old_feed_is_answered_at_once_and_read_again_behind():
    from app import churches
    churches._feed_cache["t:feed"] = (0.0, [{"id": "old"}])  # long past FEED_CACHE_SECONDS
    reads = []
    done = threading.Event()

    def load():
        reads.append(1)
        done.set()
        return [{"id": "new"}]

    assert churches._cached_feed("t:feed", load) == [{"id": "old"}]
    assert done.wait(2) and reads == [1]
    for _ in range(50):
        if "t:feed" not in churches._refreshing:
            break
        time.sleep(0.01)
    assert churches._cached_feed("t:feed", load) == [{"id": "new"}] and reads == [1]
    churches._feed_cache.pop("t:feed", None)


def test_watch_page_details():
    html = '"title":"Strength for the weary","lengthSeconds":"2900" "ownerChannelName":"Harvest House" "uploadDate":"2026-11-01T09:00:00" "shortDescription":"Isaiah 40\\nPastor Tunde"'
    details = web.watch_page_details(html)
    assert details == {"title": "Strength for the weary", "channel": "Harvest House", "date": "2026-11-01", "description": "Isaiah 40\nPastor Tunde"}


def test_clock():
    assert web.clock(400) == "6:40"
    assert web.clock(3725) == "1:02:05"


# ---------------------------------------------------------------------------
# Church websites
# ---------------------------------------------------------------------------
PAGE = """<html><head><title>Home | Hope Street Church</title>
<meta property="og:site_name" content="Hope Street Church">
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[
 {"@type":"Church","name":"Hope Street Church","address":{"@type":"PostalAddress","streetAddress":"1 Hope St","addressLocality":"Reading"},
  "sameAs":["https://www.youtube.com/@hopestreet","https://www.facebook.com/hopestreet"]},
 {"@type":"Event","name":"Carol service","startDate":"2026-12-20T17:00:00"}]}</script>
<script>var secret = "not text";</script></head>
<body><nav><a href="/visit">Plan your visit</a><a href="/events/">What's on</a><a href="https://other.org/about">Elsewhere</a></nav>
<p>Sundays at 10:30am</p></body></html>"""


def test_parse_page_reads_text_links_and_structured_data():
    page = web.parse_page("https://hopestreet.org/", PAGE)
    assert page.site_name == "Hope Street Church"
    assert "Sundays at 10:30am" in page.text and "not text" not in page.text
    assert ("https://hopestreet.org/visit", "Plan your visit") in page.links
    assert web.useful_pages(page) == ["https://hopestreet.org/visit", "https://hopestreet.org/events"]
    structured = web.from_json_ld(page.json_ld)
    assert structured["name"] == "Hope Street Church"
    assert structured["city"] == "Reading" and structured["address"] == "1 Hope St, Reading"
    assert structured["events"] == [{"title": "Carol service", "date": "2026-12-20", "time": "17:00"}]
    links = web.social_links(structured["same_as"])
    assert links == {"youtube_url": "https://www.youtube.com/@hopestreet", "facebook_url": "https://www.facebook.com/hopestreet"}


def test_merge_draft_keeps_only_sound_details():
    draft = ChurchDraft(
        name="Hope St",
        time_zone="Not/AZone",
        gatherings=[_DraftGathering(label="Sunday service", day="Sunday", time="10:30am"), _DraftGathering(label="?", day="Someday", time="9")],
        events=[_DraftEvent(title="Carol service", date="2026-12-20", time="17:00"), _DraftEvent(title="Old picnic", date="2026-06-01")],
        notices=["Parking is at the school.", "  "],
    )
    structured = {"name": "Hope Street Church", "events": [{"title": "Carol service", "date": "2026-12-20", "time": "17:00"}]}
    merged = merge_draft("https://hopestreet.org/", draft, structured, {"youtube_url": "https://www.youtube.com/@hopestreet"}, date(2026, 11, 6))
    assert merged["name"] == "Hope Street Church"
    assert merged["time_zone"] is None
    assert merged["gatherings"] == [{"label": "Sunday service", "day": 0, "time": "10:30"}]
    assert merged["events"] == [{"title": "Carol service", "date": "2026-12-20", "time": "17:00"}]
    assert [n["text"] for n in merged["notices"]] == ["Parking is at the school."]
    assert merged["website"] == "https://hopestreet.org/" and merged["youtube_url"].endswith("@hopestreet")


def test_clean_time_and_day_index():
    assert clean_time("5:30 pm") == "17:30"
    assert clean_time("12am") == "00:00"
    assert clean_time("noonish") is None
    assert day_index("Wed") == 3 and day_index("sunday") == 0 and day_index("") is None


# ---------------------------------------------------------------------------
# Notices
# ---------------------------------------------------------------------------
def test_unseen_notices_count_only_what_arrived_after_opening():
    church = {"notices_seen_at": "2026-11-05T00:00:00+00:00", "notices": [
        {"text": "Old", "added": "2026-11-01T00:00:00+00:00"},
        {"text": "New", "added": "2026-11-06T00:00:00+00:00"},
    ]}
    assert unseen_notices(church) == 1
    assert unseen_notices({**church, "notices_seen_at": None}) == 2


def test_refreshed_notices_keep_their_first_seen_time():
    old = [{"text": "Parking at the school", "added": "2026-10-01T00:00:00+00:00"}]
    new = [{"text": "Parking at the school", "added": "2026-11-06T00:00:00+00:00"}, {"text": "Carols moved", "added": "2026-11-06T00:00:00+00:00"}]
    carried = carry_notice_dates(old, new)
    assert carried[0]["added"] == "2026-10-01T00:00:00+00:00"
    assert carried[1]["added"] == "2026-11-06T00:00:00+00:00"


# ---------------------------------------------------------------------------
# The week after a sermon
# ---------------------------------------------------------------------------
def test_week_steps_come_from_the_note():
    note = {
        "passage_ref": "Isaiah 40:28-31",
        "passages": ["Isaiah 40:28-31", "Matthew 11:28"],
        "blocks": [{"type": "todo", "items": [{"text": ""}, {"text": "Take a real rest day"}]}],
        "week": {"question": "Where are you trying to be strong alone?", "done": {"reread": True}},
    }
    steps = {s["key"]: s for s in week_steps(note)}
    assert list(steps) == ["reread", "learn", "question", "act", "pray"]
    assert steps["reread"]["ref"] == "Isaiah 40:28-31" and steps["reread"]["done"]
    assert steps["learn"]["ref"] == "Isaiah 40:28-31"
    assert steps["question"]["text"].startswith("Where are you")
    assert steps["act"]["text"] == "Take a real rest day"


def test_week_steps_without_a_passage_skip_the_reading_steps():
    keys = [s["key"] for s in week_steps({"passages": [], "blocks": [], "week": None})]
    assert keys == ["question", "act", "pray"]


def test_a_whole_chapter_is_learned_from_its_first_verse():
    steps = {s["key"]: s for s in week_steps({"passage_ref": "Psalm 23", "passages": ["Psalm 23"], "blocks": []})}
    assert steps["learn"]["ref"] == "Psalm 23:1"


# ---------------------------------------------------------------------------
# Sermon notes from a link
# ---------------------------------------------------------------------------
def test_note_from_draft_keeps_only_real_passages_and_the_preachers_words():
    draft = SermonDraft(
        title="Strength for the weary",
        speaker="Pastor Tunde",
        main_passage="Isaiah 40:28-31",
        passages=["Matthew 11:28", "the book of Hezekiah 3:1"],
        points=[_Point(at_seconds=400, text="God does not grow tired."), _Point(text="  ")],
        quote=_Quote(text="Some of you came in running on empty."),
        todos=["Take a real rest day"],
        question="Where are you trying to be strong alone?",
    )
    source = {"video_id": "bbbbbbbbbbb", "url": "https://www.youtube.com/watch?v=bbbbbbbbbbb", "details": {}}
    note = note_from_draft(draft, source, {"name": "Harvest House"}, date(2026, 11, 1))
    kinds = [b["type"] for b in note["blocks"]]
    assert note["passage_ref"] == "Isaiah 40:28-31"
    assert [b["ref"] for b in note["blocks"] if b["type"] == "verse"] == ["Isaiah 40:28-31", "Matthew 11:28"]
    assert "• 6:40 God does not grow tired." in next(b["text"] for b in note["blocks"] if b["type"] == "text")
    assert kinds.count("quote") == 1 and kinds[-1] == "link"
    assert note["church"] == "Harvest House" and note["week"]["question"].startswith("Where")


def test_a_quote_that_is_really_a_verse_is_left_out():
    draft = SermonDraft(title="x", quote=_Quote(text="As Isaiah 40:31 says, they will run"))
    note = note_from_draft(draft, {"video_id": None, "url": "https://example.org/ep", "details": {}}, None, date(2026, 11, 1))
    assert "quote" not in [b["type"] for b in note["blocks"]]
    # No timestamps without a video to jump to.
    assert note["blocks"][-1]["label"] == "Listen again"


# ---------------------------------------------------------------------------
# Reading real-world church sites, YouTube channels and podcasts. Each case
# below is shaped after a site that tripped the reading up once.
# ---------------------------------------------------------------------------
def test_words_in_neighbouring_tags_stay_apart():
    page = web.parse_page("https://hope.org/", "<nav><a>Sermons</a><a>Locations</a><span>About</span></nav><p>Sundays <b>10am</b></p>")
    assert "Sermons Locations About" in page.text and "Sundays 10am" in page.text


def test_youtube_links_found_in_scripts_too():
    html = '<script>var footer = {"yt":"https:\\/\\/www.youtube.com\\/@hopestreet"};</script>'
    assert web.parse_page("https://hope.org/", html).mentions == ["https://www.youtube.com/@hopestreet"]


@pytest.mark.parametrize("href, channel", [
    ("https://www.youtube.com/@hopestreet/videos", "https://www.youtube.com/@hopestreet"),
    ("https://www.youtube.com/saddlebackchurch", "https://www.youtube.com/saddlebackchurch"),
    ("https://youtube.com/channel/UCkvTYtzvEDc7i0ATeWC-wHg?sub=1", "https://www.youtube.com/channel/UCkvTYtzvEDc7i0ATeWC-wHg"),
    ("https://www.youtube.com/watch?v=bbbbbbbbbbb", None),
    ("https://www.youtube.com/results?search_query=church", None),
    ("https://vimeo.com/hopestreet", None),
])
def test_youtube_channel_url(href, channel):
    assert web.youtube_channel_url(href) == channel


def test_social_links_prefer_a_readable_podcast_and_keep_a_video_to_find_the_channel():
    links = web.social_links([
        "https://open.spotify.com/show/abc?si=x",
        "https://www.youtube.com/watch?v=bbbbbbbbbbb",
        "https://hope.podbean.com",
        "https://podcasts.apple.com/us/podcast/hope/id123",
        "https://www.facebook.com/sharer/sharer.php?u=x",
        "https://www.facebook.com/hopestreet",
        "https://hope.org/blog/feed/",
    ])
    assert links == {
        "youtube_video": "https://www.youtube.com/watch?v=bbbbbbbbbbb",
        "podcast_url": "https://podcasts.apple.com/us/podcast/hope/id123",
        "facebook_url": "https://www.facebook.com/hopestreet",
    }


def test_useful_pages_take_the_best_of_each_kind_and_skip_news_slugs():
    page = web.Page(url="https://www.hope.org/", links=[
        ("https://www.hope.org/news/a-word-from-our-pastor-on-the-move", "A word from our pastor on the move, and what comes next"),
        ("https://hope.org/learn-more-about-stephen", "Learn more"),
        ("https://hope.org/about-us", "About"),
        ("https://hope.org/whats-on", "What's on"),
        ("https://hope.org/plan-a-visit", "Plan a visit"),
        ("https://hope.org/services", "Services"),
        ("https://hope.org/bulletin.pdf", "Bulletin"),
        ("https://other.org/visit", "Visit"),
    ])
    assert web.useful_pages(page) == ["https://hope.org/plan-a-visit", "https://hope.org/whats-on", "https://hope.org/about-us"]
    assert web.useful_pages(page, limit=4)[-1] == "https://hope.org/services"


def test_site_text_shares_the_room_and_leaves_out_repeated_menus():
    menu = "Home About Visit Give Events Sermons Contact"
    home = web.Page(url="https://hope.org/", title="Home", text=f"{menu}\n" + "Welcome home. " * 400)
    visit = web.Page(url="https://hope.org/visit", title="Visit", text=f"{menu}\nSundays 9am and 11am")
    text = web.site_text([home, visit], 1000)
    assert len(text) <= 1000 and text.count(menu) == 1
    assert "Sundays 9am and 11am" in text  # the visit page isn't crowded out by the homepage


@pytest.mark.parametrize("label, days", [
    ("2 days ago", 2), ("Streamed 3 weeks ago", 21), ("1 month ago", 30), ("1y ago", 365),
    ("5 hours ago", 0), ("2d ago", 2), ("1.7 thousand views", None),
])
def test_days_ago(label, days):
    assert web.days_ago(label) == days


def _lockup(video_id, title, ago, length="51:49", kind="LOCKUP_CONTENT_TYPE_VIDEO"):
    return {"lockupViewModel": {
        "contentId": video_id, "contentType": kind,
        "contentImage": {"thumbnailViewModel": {"overlays": [{"thumbnailBottomOverlayViewModel": {"badges": [{"thumbnailBadgeViewModel": {"text": length}}]}}]}},
        "metadata": {"lockupMetadataViewModel": {"title": {"content": title}, "metadata": {"contentMetadataViewModel": {"metadataRows": [
            {"metadataParts": [{"text": {"content": "Hope Street"}}]},
            {"metadataParts": [{"text": {"content": "1.2K"}, "accessibilityLabel": "1.2 thousand views"}, {"text": {"content": ago}}]},
        ]}}}},
    }}


def test_channel_page_lists_videos_with_their_age_as_a_date():
    import json
    items = [
        _lockup("aaaaaaaaaaa", "Strength for the weary", "2 days ago"),
        _lockup("aaaaaaaaaaa", "Strength for the weary", "2 days ago"),  # shown twice on the page
        _lockup("ccccccccccc", "Sunday service, live", "", length="LIVE"),  # live now: no age yet
        _lockup("ddddddddddd", "A playlist", "1 week ago", kind="LOCKUP_CONTENT_TYPE_PLAYLIST"),
    ]
    html = f"<script>var ytInitialData = {json.dumps({'contents': items})};</script>"
    videos = web.parse_channel_page(html, date(2026, 11, 13))
    assert videos == [{
        "id": "yt:aaaaaaaaaaa", "video_id": "aaaaaaaaaaa", "title": "Strength for the weary", "published": "2026-11-11",
        "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa", "length": "51:49", "description": "",
    }]
    assert web.parse_channel_page("<html>no data</html>", date(2026, 11, 13)) == []


def test_podcast_dates_and_lengths_are_plain():
    xml = """<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel>
    <item><title>One</title><guid>1</guid><pubDate>Sun, 09 Nov 2026 10:00:00 GMT</pubDate><itunes:duration>2712</itunes:duration><enclosure url="https://cdn.example.com/1.mp3"/></item>
    <item><title>Two</title><guid>2</guid><pubDate>not a date</pubDate><itunes:duration>01:05:00</itunes:duration><enclosure url="https://cdn.example.com/2.mp3"/></item>
    </channel></rss>"""
    one, two = web.parse_podcast_feed(xml)
    assert (one["published"], one["length"]) == ("2026-11-09", "45:12")
    assert (two["published"], two["length"]) == ("", "1:05:00")


def test_a_watch_page_names_its_own_videos_channel():
    html = '"channelId":"UCaaaaaaaaaaaaaaaaaaaaaa" ... "videoDetails":{"videoId":"bbbbbbbbbbb","title":"x","channelId":"UCkvTYtzvEDc7i0ATeWC-wHg"}'
    assert web.video_channel_id(html) == "UCkvTYtzvEDc7i0ATeWC-wHg"


def test_a_blocked_site_says_so():
    assert "doesn't let Adullam read it" in web._status_message(403)
    assert "wasn't found" in web._status_message(404)


def test_notes_on_a_podcast_episode_come_from_its_feed():
    from app import churches
    episode = {"id": "pod:1", "title": "Fixate on Him", "url": "https://cdn.example.com/1.m4a", "audio_url": "https://cdn.example.com/1.m4a",
               "published": "2026-11-11", "description": "On Hebrews 12:2."}
    churches._feed_cache["catalog:cymbala"] = (time.monotonic(), [episode])
    try:
        source = churches._source_for("https://cdn.example.com/1.m4a")
        assert source["words"] == "Fixate on Him\n\nOn Hebrews 12:2."
        assert source["details"]["channel"] == "Brooklyn Tabernacle" and source["details"]["date"] == "2026-11-11"
        with pytest.raises(web.FetchError, match="recording itself"):
            churches._source_for("https://cdn.example.com/unknown.mp3")
    finally:
        churches._feed_cache.pop("catalog:cymbala", None)
