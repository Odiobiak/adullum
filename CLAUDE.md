# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Adullum is a Bible study agent named Aquila: ask a Scripture question, get a grounded answer with chapter-and-verse citations, never an invented reference. Built as a learning project (LangGraph + Supabase + FastAPI) designed to grow: chat today, voice and mobile later.

## Commands

```bash
pip install -e ".[dev]"                                  # install app + dev deps
uvicorn app.main:app --reload --reload-dir app --reload-dir web   # one process: REST API, SSE, MCP server, and the web UI all at :8000
                                                          # (--reload-dir keeps OneDrive syncing .venv from restarting the server mid-request)
python scripts/fetch_translation.py --translation KJV   # download KJV/ASV/WEB/BSB to data/kjv.json in the shape ingest.py reads
python scripts/ingest.py --file data/bsb.json --translation BSB   # load a translation into Supabase; only BSB (the search translation) is embedded, the rest go in as text
python scripts/ingest_cross_references.py                # load classic cross-references for Connections (after its migration); downloads the data if needed
python scripts/set_password.py someone@example.com      # set or reset an account's password from the terminal (prompts for it, never echoes)
python scripts/make_vapid_keys.py                        # make the key pair that signs push notifications; put both lines in .env and on Render
python scripts/set_supporter.py someone@example.com     # mark a monthly giver as a friend of the cave (--remove when they stop)
pytest                                                    # run the test suite (tests/)
```

Config lives in `.env`, read once into `app/config.py::settings`. `tests/conftest.py` sets dummy Supabase/OpenAI credentials so the suite runs without a real `.env` (in CI, in particular); the suite itself only covers pure logic (`app/retrieval.py`'s parsers, `app/schemas.py`, the graph's routing functions) and the API contract with the compiled `agent` mocked out in `tests/test_api.py`. Nothing in it makes a real LLM or Supabase call. `.github/workflows/test.yml` runs it on every push and PR.

## Always
When writing code, always write code like a good human software engineer. Always use the best coding practice and naming convention. Make sure the code is very well documenteted, readable and easy to follow. Design for less wordings and less space usage.

## Architecture

One FastAPI process (`app/main.py`) serves three things off the same LangGraph agent, so there is exactly one place Aquila's behavior is defined:
- `POST /chat` and `POST /chat/stream` for the web client
- `/mcp/sse`, an MCP server (`app/mcp_server.py`) exposing an `ask_aquila` tool, meant for Cognigy's MCP Tool Node or any other MCP client
- `web/index.html` mounted as static files at `/`, so a single deploy needs no separate frontend host

### The agent graph

`app/agent/graph.py` wires the nodes in `app/agent/nodes.py` using the state in `app/agent/state.py`:

```
(mode="listen") --> listen --> END                      Refuge's Aquila, see below
(mode="pray")   --> pray_with --> END                   Pray with Aquila, see below

classify_intent --meta--> answer_meta --> END
       |
     other
       v
   retrieve --> synthesize --> ground_check --ungrounded, retries left--> retrieve (wider k)
                                     |
                                grounded, or retries exhausted
                                     v
                              format_citations --> suggest_followups --> END
```

`suggest_followups` runs last deliberately: the answer and citations have already
streamed to the client by then, so its extra LLM call costs no perceived latency.
It is also non-fatal, returning an empty list on failure rather than sinking an
answer that was otherwise complete and grounded.

`pray_with` is "Pray with Aquila" on the prayer list (`web/prayers.js` sends
`mode: "pray"` to `/chat/stream`): three parts under their own headings
(`## Scripture to hold onto`, `## A prayer`, `## Keep praying`), no study and no
follow-ups. It uses the same reference check as `listen` below, rewriting once
and then praying without Scripture rather than quoting an unlisted verse.

`listen` is the same Aquila in Refuge (`app/refuge.py` sets `mode="listen"` and the
whole talk as `history`): no headings, no follow-ups, one gentle reply. It still
never invents a verse. It looks verses up only when Scripture is wanted, and
`unlisted_references` checks every reference in the reply against what was looked
up, rewriting once and then dropping Scripture altogether. A care check (the model,
plus the phrases in `app/care.py`, which always count) sets `care`, and the client
shows helplines under the reply. Keep `LISTEN_SYSTEM_PROMPT`'s house-style line if
you touch it.

### The shape of an answer

`SYNTHESIZE_SYSTEM_PROMPT` asks for three Markdown headings (`## The passage`,
`## Context`, `## To think about`), which the web client renders as ruled section
headings and `suggest_followups` extends with a "Keep going" block.

**Fact is stated; meaning is offered.** This is the product's stance, not a style
choice: Aquila is a place to rest and learn, never one that presses a meaning on
anyone. What the text says and what the verses themselves show (who speaks, to
whom, what happens) goes in "The passage" and "Context", plainly and cited.
Every reading of a passage (what it means, teaches or asks of someone) goes only
in "To think about", offered as threads to consider and ending with a question,
never as a conclusion ("this means", "this teaches us" are out). There was a
"What it means" heading once; it was removed for exactly this reason, so don't
bring it back. `GROUND_CHECK_PROMPT` knows a reflection offered as a question is
not a claim, while an interpretation stated as fact still has to be supported.

Under each answer stay two quiet lines and nothing more: the references as plain
links (they open Connections), then Bible, Connections, Save, and Listen and
Share as icons (`cave.js::decorateAnswer`). Save is one tap into Saved in the Bible (a second tap takes it back out). The "Close to..." strip of related
verses was removed, since Connections already shows them.
Two things depend on that format, so changing the headings means changing both:
`web/index.html::renderAnswerHtml` (which strips the surrounding newlines so the
Markdown's blank lines don't stack on top of the heading's own margin) and
`app/mcp_server.py::_spoken` (which turns the headings back into sayable
sentences, since a voice gateway reads the tool's answer string verbatim and
would otherwise pronounce the hashes).

The `meta` intent exists because `synthesize` is hard-instructed to answer only from retrieved verses. Before this branch existed, a question like "what's your name?" would retrieve unrelated verses about names and Aquila would dodge the question instead of just answering as herself. Anything that is not actually a Bible-content question should route here, not through retrieval.

### Retrieval (`app/retrieval.py`)

`hybrid_retrieve` tries three paths and merges/dedupes the results, reference hits first:
1. **Reference regex** (`parse_reference`) for a book name immediately followed by a chapter number.
2. **Book-of-X detection** (`parse_book_mention`) for a book named with no chapter (e.g. "the Book of James"), which pulls that book's opening verses directly rather than letting a book-overview question drift across the whole corpus via unscoped vector search. Deliberately narrow (`book of X` phrasing only, not any bare book name), because several book names (Job, Mark, Acts, Titus, James, John, Ruth) are also common English words and would false-positive on unrelated questions.
3. **Vector search** via the `match_verses` Postgres RPC (`supabase/schema.sql`), and **keyword search** over a generated `tsvector` column, topping up whatever the first two didn't fill.

Embeddings are kept small on purpose, because a 1536-dimension vector on every verse of four translations once filled the 2 GB disk and put the project in read-only mode (`supabase/migrations/20261108_compact_embeddings.sql` explains and fixes it; run it once, after the others):
- **Only `settings.search_translation` (BSB) is embedded.** `match_verses` finds the nearest BSB verses and returns the same book, chapter and verse from the requested translation, so every translation still gets semantic search. `scripts/ingest.py` stores the others as text only. Changing the search translation means re-ingesting the new one with embeddings and updating the `'BSB'` in that migration.
- **512 dimensions at half precision** (`halfvec(512)`), about 1 KB a verse. `embed_query` and the ingest both ask OpenAI for `dimensions=settings.embedding_dim`; `text-embedding-3` models are built so that this matches shortening a full embedding and rescaling it, which is how the migration converted the stored ones without re-embedding. Verse search and memories (`user_memories`) share `embed_query`, so they must stay the same size.
- **The index is HNSW**, which keeps itself current as rows are added. There is no rebuild step after an ingest.

### Observability (`app/observability.py`)

Langfuse SDK v4. The module docstring documents three non-obvious failure modes already hit and fixed once, read it before touching this file:
- `os.environ` must actually have `LANGFUSE_*` set (pydantic-settings reads `.env` into its own object without touching `os.environ`; the Langfuse SDK reads `os.environ` directly). `load_dotenv()` in `app/config.py` handles this.
- The per-request `CallbackHandler` must never be cached or shared across requests. It exposes the trace it created via the plain instance attribute `last_trace_id`, and sharing one instance would race that attribute across concurrent requests.
- Scoring a trace from inside a node function must use that explicit `last_trace_id`, not Langfuse's ambient "current trace" context. LangGraph runs sync node functions on a worker thread that does not inherit the main coroutine's contextvars, so the ambient lookup fails there.

### The cave: accounts, journal, plans, memory (`app/auth.py`, `app/cave.py`, `app/reading_plans.py`, `app/memory.py`, `web/cave.js`)

Run the files in `supabase/migrations/` once each, in date order, in the Supabase SQL editor (`20261104_my_cave.sql`, `20261105_hearth.sql`, `20261106_plan_titles.sql`, and on through `20261119_declarations.sql`). Until the first runs, `/me/*` returns a 503 that says so and chat quietly runs as a guest; until the second, the home screen hides its embers and "Mark as read" explains what to run; until the third, plans shaped with Aquila save without their title and show a generic one.
- **Auth is brokered by this server.** The browser never holds a Supabase key. `/auth/*` signs people in on a throwaway client from `app/auth.py::_auth_client` (never the shared `get_supabase()` one, which a sign-in would switch to that user's token), using the implicit flow so magic-link tokens land in the URL fragment for `web/cave.js` to pick up. Magic links only return here if the site URL is listed under Supabase Auth > URL Configuration.
- **Every `/me` query filters by `user_id` in code**, because the service-role client bypasses RLS. The RLS policies in the migration exist for a future client talking to Supabase directly.
- **The home screen is one request.** `GET /me/home` (`app/hearth.py`) gathers embers, the last conversation, today's plan reading, the prayer list at a glance (with `prayed_today`), the person's active habits from Pebbles, a glance at the Amens wall, a journal entry to revisit and two memories (the screen doesn't show the memories; they live in Settings), each part failing to null on its own. Days are the browser's local days (it sends `today`, checked by `app/days.py::parse_today`), so a streak doesn't break at a UTC midnight.
- **The home screen stays quiet** (`cave.js::showHome`). Top to bottom: the greeting with the streak as one small ember chip (a tap shows the week), notification lines (`homeNote`: a church live, Amens) only while there is something to tell, the ask box, the verse for today (Reflect, everything else in "⋯"), then Today (`todayCard`: the plan's reading, Pray and up to three habits, each a row with a circle to tick, "Start a reading plan" when there's none), with the last conversation, a journal entry to revisit and Support in the side column. A part with nothing to say isn't drawn. Keep anything new to a row in an existing list rather than a new card, and keep pills off this page.
- **Verse text on screen always comes from the database.** The verse of the day (`app/hearth.py::VERSES_OF_THE_DAY`), the welcome page's example passage and the signed-out page's verse are fetched through `/verse-of-the-day` and `/verse`, never typed into the page. The only hard-coded quotation is the KJV 1 Samuel 22 passage that explains the name, and it is labelled KJV.
- **Plans shaped with Aquila can't invent a chapter.** `POST /me/plans/build` asks the model only for books and chapter ranges (`app/plan.py::PlanDraft`). `expand_sections` resolves every book through `app/retrieval.py::canonical_book`, clamps ranges to `BOOK_CHAPTER_COUNTS`, and the split into days is the same arithmetic as the whole-Bible plan. Keep the model out of the day-by-day layout.
- **Memory is never Scripture.** `app/memory.py::recall` hands the graph `memories` for signed-in people; `synthesize`, `answer_meta` and `ground_check` all label them as notes about the person that can't support a claim about the Bible. Keep that labelling if you touch those prompts. Note-taking (`remember_turn`) runs after the answer is delivered and is non-fatal, like `suggest_followups`.

### Prayers and fasting (`app/prayers.py`, `app/fasting.py`, `web/prayers.js`)

Run `supabase/migrations/20261109_prayers_highlights_memorize.sql` once, after the others. Until then the prayer list (and highlights) return a 503 that says what to run, and Pray doesn't appear in the home's Today list. It also made `memory_verses`, which nothing reads now that Saved replaced Memorize.
- **A prayer is open until it's marked answered**, with an optional line on how; it can be reopened. When memory is on, `prayers.py::_remember` keeps one memory note per prayer (`user_memories.prayer_id`, deleted with it, rewritten when it's answered or edited), so Aquila can bring an open request up. Same "never Scripture" labelling as every memory.
- **The Prayers tab tracks praying and fasting** above the list (`supabase/migrations/20261112_pebbles_and_prayer_practice.sql`; until it runs, those two cards give way to one line saying what to run and the list still works). "This week" is seven days lit on any day the person prayed (`prayer_days`, `prayers.py::prayer_week`), with an "I prayed today" button (a row with no `prayer_id`); each open request has its own "Prayed today" toggle, which lights the day too. Fasting (`fasts`, `app/fasting.py`) is a kind (water only, Daniel, a meal, something else), a number of days (1 to 40) and what it's for; the card shows "Day 2 of 21" (`fasting.py::fast_progress`), and finishing takes an optional reflection. A fast is never judged: finishing before the last planned day is still finishing. Days are counted, never shown as a streak, and a day can be marked up to a week back (`days.py::parse_markable_day`). Neither feeds Aquila's memory.

### Declare (`app/declare.py`, `web/declare.js`)

Scripture spoken aloud, in faith, over something a person is facing: they say what it is and get an opening line ("In the name of Jesus, I declare God's word over..."), three to five lines to say aloud, each with the verse it rests on, and Amen. `#declare` is the page, `#declare/<id>` a kept one. Three ways in: the home screen's one line (for oneself, its explanation behind an info button), "Declare over" on a prayer card, and "Declare" in the Prayers tab's New menu (`cave.js::newPrayerMenu`, for something right now, with an optional name). Run `supabase/migrations/20261119_declarations.sql` once, after the others; until then the words still come and Keep says what to run.
- **Aquila only picks references.** `nodes.py::suggest_declare_refs` names passages (one verse or a run of up to three), an ordinary `hybrid_retrieve` runs beside it, and every verse's words are read from the verses table. `nodes.py::write_declaration` writes the lines from those passages, and `declare.py::usable_lines` keeps a line only when its reference is one she was given and its words name none of their own; too few survive and she writes again once, none and the person is asked to put it another way. Kept declarations store each line's words and reference, never verse text. Not a graph node: two structured calls, the first run alongside the search, about five seconds in all.
- **What a line may say**: what its own passage says, with its conditions kept ("as I walk with the Lord"), present tense, "I" for oneself and "you" over someone else. Never "God told me", never a promised outcome ("you will get the job"). Keep those rules in `DECLARE_SYSTEM_PROMPT`.
- **Private and personal.** No sharing, nothing reaches `user_memories`, and every query filters by `user_id`. A declaration over a prayer is kept with it (one per prayer, deleted with it); a quick one becomes a prayer when kept; one for oneself is listed under the form. A situation that sounds unsafe (`care.py::sounds_unsafe`) gets helplines and Refuge instead of words (`refuge.js::helplineRows`).
- "Speak it aloud" is full screen, one line at a time, with the screen kept awake where the browser allows. There's no read-aloud voice yet: good speech costs money, and the device's built-in voices are the free option if it's ever wanted.

### Refuge and the admin desk (`app/refuge.py`, `app/one_another.py`, `app/care.py`, `web/refuge.js`)

A quiet room in the cave for every kind of season, not only hard ones. Run `supabase/migrations/20261110_refuge.sql` once, after the others; until then the tab shows the setup message. Five rooms, drawn in place inside the tab (not hash routes, so Refuge is one history entry and Back never leads from one room into another):
- **Write it out**: a blank page or a guided shape (lament, thanks, hoping). "Let it go" never touches the server; only "Keep it" stores anything (`refuge_writings`). "Make it a goal" turns a hope into a Pebbles goal, its first small step as the goal's first step.
- **Talk with Aquila**: the graph's `listen` node through `POST /me/refuge/talk`. The browser holds the talk, and it vanishes when the person leaves Refuge (`Refuge.hide`, called by `cave.js` on any other tab or view) unless they press Keep (`refuge_talks`). These runs pass `callbacks: []`, so they are never traced to Langfuse, and nothing here reaches `user_memories`. Keep both true.
- **Pebbles** (once "Grow"; the code still says seeds): goals and habits, in `refuge_seeds` and `refuge_checkins` (`20261112_pebbles_and_prayer_practice.sql` added the columns below, moved the old prayer pebbles onto the prayer list and turned hopes into goals). A goal is tracked one way (`refuge.py::goal_tracking`): steps, a number ("4 of 12 books", `target`/`progress`/`unit`, with − and + on the card), or just marked reached, optionally by a date (`due_on`). A habit is meant for `per_week` days and shows this week as dots (`cave.js::weekDots`, tappable for the days so far), counted as "3 of 5 this week", never as a streak. Each card shows one next action and keeps the rest in a "⋯" menu (`cave.js::moreMenu`). Praying and fasting belong on the prayer list, not here.
- **Be still**: a guided pause (`refuge.js::stillRoom`). The person picks a breath prayer, a rhythm (Calm, Even, Box, Deep rest) and a length, then a full-screen session breathes a light in time with each part of the breath, with a progress ring, pause, optional soft tones made in the browser and a screen wake lock, and ends by asking how they are ("Still heavy" points to Aquila, Write it out or a person). A breath prayer's words are never typed in: each is a reference read from the database in the open translation and cut in two by `breathHalves`, the first half on the breath in and the second on the breath out. Nothing reaches the server; the choices and this week's count stay in the browser's storage.
- **Amens** (first called "One another", which `app/one_another.py` and the `refuge_*` tables still say): share a burden or good news without a name. The two kinds are named as the ask they are, "Pray for me" and "Rejoice with me" (`refuge.js::POST_KINDS`), chosen in a compact composer that opens when tapped, and the info button beside the room's title opens "How Amens works" (`refuge.js::HOW_AMENS_WORKS`); keep that in step if the wall's rules change. A person's own posts that are still waiting for approval sit in their own zone under the share box (`refuge.js::waitingZone`), apart from "What you've shared", which holds only posts that have been through review. Saying amen is the one reaction, one count per person on the server, but on screen it reads as what it means (`refuge.js::REACTIONS`): a burden's button is "Say a prayer" and good news's "Rejoice with them", and once pressed either turns to "Amen", agreeing with the prayer, with "You and 4 others prayed for this" beneath. The writer's own posts sit above the wall as a row of small bubbles (`refuge.js::mineBubble`) showing their status or counts, and a tap opens one in a sheet, where they see what came back as people ("12 people prayed for you") with anonymous faces, never who, and a post's count is its amens. A post goes through `one_another.screen` (contact details refused; signs of risk are not posted and the writer is shown helplines; OpenAI moderation refuses hate, harassment, sexual and illicit content, while violence goes to a person since it also catches someone describing harm done to them), then goes up straight away when the check flagged nothing and ran (`one_another.goes_up_now`), or waits as `pending` on the **admin desk** (`#desk`, `/admin/refuge`) until someone in `ADMIN_EMAILS` approves it; `AMENS_AUTO_APPROVE=false` sends every post to the desk. A report takes it off the wall at once and back to the desk.
- **The wall at scale** (`supabase/migrations/20261116_amens_at_scale.sql`; until it runs, the wall says what to run). No followers and no feeds: each person's wall is the database function `amens_wall`, posts by others from the last month that they haven't said amen to first, then those with the fewest amens, in a shuffle seeded by who's looking, a page at a time ("Show more"), so prayer spreads across every request. Counts live on the post (`amen_count`, `kind_word_count`, kept by triggers) and amens per day in `refuge_amen_days`; never count amens by loading their rows, since an answer stops at 1,000. The home notice counts posts gone up since the person last opened the wall (`refuge_wall_visits`) that they haven't said amen to. A writer with new amens gets one notification in their evening (`one_another.run_digest`, run by `app/reminders.py`'s loop and its cron route, claimed once per writer by `claim_amens_digest`; `profiles.amens_digest` turns it off from a switch under "What you've shared", and `profiles.time_zone` is kept by `cave.js::loadProfile`). The database functions are callable by the service role only, since `amens_digest_due` returns who wrote posts.
- **How long a post stays** (`supabase/migrations/20261117_amens_lifetimes.sql`, `one_another.LIFETIME_DAYS`): a prayer request two weeks from when it goes up, which its writer can keep up two weeks more at a time once it's within four days of its end or just past it, up to two months (`kept_up_until`, `POST .../keep-up`, offered by `refuge.js::keepUpNudge` under the share box and on the post); good news a week; a prayer marked answered (`POST .../answered`, with an optional line on how) five more days, shown on the wall as good news and taking good-news kind words. Then it leaves the wall for everyone else (`expires_at`, read by `amens_wall`); the writer's own copy stays, shown "Off the wall". The rules are spelled out once in `refuge.js::HOW_LONG`, shown in "How Amens works" and behind the info button on each of the writer's posts; keep both in step with the server. Others can only say amen, send one of `KIND_WORDS` (verses stored by reference and read from the database), or report. Nobody, the desk included, is ever sent who wrote a post; keep `user_id` out of every wall and desk select.

Helplines live in `web/refuge.js::HELPLINES`, chosen by the browser's region and changeable. Nothing anyone writes, talks through or shares in Refuge appears on the home screen. Two exceptions are deliberate: the person's own active habits (rows in Today, linking to `#pebbles`), and, public, the home's Amens notice (`one_another.py::amens_glance`, drawn by `refuge.js::homeCard`) sits at the top of the home screen as one tappable line, like a notification: how many posts by other people are waiting for this person's amen (a count on the icon) and this week's amens across the whole wall. It opens `#amens`, and it stays hidden when there is nothing to tell. Never put the person's own posts, or anything that shows they posted, on that card.

### The Bible reader, notes and highlights (`app/bible.py`, `app/notes.py`, `app/highlights.py`, `web/reader.js`)

Anyone can read; notes, highlights and saving need an account. Run `supabase/migrations/20261107_verse_notes.sql` once, after the others (and `20261109_...` for highlights). Until then the reader works and saving returns a 503 that says what to run.
- **A translation is offered only once it's loaded.** `app/bible.py::TRANSLATIONS` lists the public-domain ones (BSB, KJV, WEB, ASV); `/bible/translations` returns the subset that has verses in the database, cached for five minutes, so after ingesting a new one the picker shows it within that window. To add one, fetch it with `scripts/fetch_translation.py` (which normalizes book names and the quirks of each source, listed in its docstring), ingest it, and it appears. It is stored as text only and borrows BSB's embeddings for vector search (see Retrieval above).
- **One translation preference drives everything.** The hidden `#translation` input in `index.html` is the single value Aquila, the verse of the day, Connections and the reader all read. `web/reader.js` sets it from the reader's picker and the one in Settings, remembers it on the device, and saves it to `profiles.preferred_translation` when signed in (applied on the next sign-in via the `adullum:profile` event `cave.js` dispatches).
- **Notes are pinned to book, chapter and verse range, not to a translation**, so a note shows beside the same verse whichever translation is open. `translation` and `verse_text` record what the person was reading when they wrote it. Every `/me/notes` query filters by `user_id`, same rule as the cave.
- **Highlights follow the same rule**, one colour per verse (gold, green, blue, rose), stored a row per verse so overlapping highlights never conflict. The server reads each verse's text from the verses table when it saves one, and `highlights.py::group_highlights` joins neighbouring verses of one colour back into a passage for My notes. The colours are `--hl-*` tokens in all four themes.
- **Asking Aquila about a verse or note is an ordinary question** composed by `reader.js::askQuery` with the reference first (`On John 3:16-18: ...`), so `parse_reference` pulls exactly those verses and nothing in the graph changes. A note goes in quoted as the person's own words; the synthesize prompt still grounds only on retrieved verses, so a note can't become a citation.
- **The Bible tab opens on a front page** (`#bible`, `reader.js::showHub`) with four ways in: Bible (carrying on at the chapter last read on this device), Reading plans, My notes and Saved, so it's plain the tab holds more than the text. Signed in, the last three show how many plans still have today's reading to do, how many notes and highlights are kept and how many things are saved. A bare `#bible` link always lands there; anything that should open a chapter links to one.
- Reader links are `#bible/<Book-with-hyphens>/<chapter>[/<verse>]`; `Reader.href("John 3:16")` builds one. "Bible" under each answer and "Read in context" in the Connections side panel use it.

### Saved (`app/saved.py`, `web/saved.js`)

One place for everything saved with one tap, in the Bible tab (`#bible/saved`), where Memorize used to be. Run `supabase/migrations/20261118_saved.sql` once, after the others; it also copies anyone's memory verses in. Until then saving returns a 503 that says what to run.
- **Two kinds, newest first**: a verse (Save on the reader's verse bar, the verse for today's "⋯", a sermon's week after) and an answer from Aquila (Save under it). The page filters them with one dropdown.
- **A verse's words are read from the verses table by the server**, never sent by the browser. Saving the same passage again returns the one already saved (a partial unique index), so Save is safe to tap twice.
- **Writing stays in the Journal.** A saved item's "⋯" offers "Write about it", which opens the journal sheet with it; Save itself never asks for words.

### Sermon notes (`app/sermons.py`, `app/sermon_export.py`, `web/sermons.js`)

Sermon notes are the Sermons part of the Church tab (`#church/sermons`; `#sermons` lands there), drawn by `sermons.js` into `church.js`'s page. Run `supabase/migrations/20261111_sermon_notes.sql` once (it also creates the private `sermon-images` storage bucket). Until then Sermons says what to run.
- **The tab opens on the list.** A note opens only when it's picked (`sermons.js::showList` and `openNote`), then sits beside the list; on a phone it takes the list's place, with "All sermons" to go back.
- **A note is details plus blocks.** Title, speaker, church, date, series and main passage, then an ordered list of blocks (`text`, `heading`, `verse`, `image`, `quote`, `todo`, `link`) stored as JSON and validated by the pydantic models at the top of `app/sermons.py`. The page saves the whole note about a second after each edit.
- **Lists are plain text.** A bullet is a line starting `• `, a numbered item a line starting `1. `. In a text block, Enter carries a list on, Enter on an empty item ends it, `- ` or `* ` at a line's start becomes a bullet, and the block's tools toggle either kind (`sermons.js::toggleList`, `onListKeys`); "List" in the Add bar is a text block that starts with a bullet. Nothing new is stored, so the shared page and PDF and Word exports show them as written, and `sermon_export.markdown_text` turns them into Markdown lists and keeps the line breaks Markdown would otherwise join.
- **The server finds the references, not the page.** Each save runs every block through `retrieval.find_references` and returns `passages` (the whole note, main passage first) and `block_refs` (per block), which the page shows as chips linking to the reader. Verse blocks store only the reference; their text is always read from the database in the reader's translation, on screen and in exports.
- **Photos** are shrunk in the browser to 1600 pixels, sent as base64, checked by their first bytes, and stored under `<user id>/<note id>/` in the `sermon-images` bucket. A block keeps only the path, `clean_blocks` refuses any path outside the note's own folder, and the server signs an hour-long link each time the note is read. Photos dropped from a note, or in a deleted note, are removed from storage.
- **Sharing is a read-only link** (`#sermon/<token>`, `GET /shared/sermons/{token}`, no account needed). `shared_view` strips the user id, storage paths and prayer ids before anything leaves the server. Stopping sharing clears the token, so the old link dies for good. Links in a note are kept to http(s) only, since strangers open shared notes.
- **Export**: one note as PDF, Word or Markdown (`GET /me/sermons/{id}/export?format=`), or every note as Markdown plus photos in one zip (`/me/sermons/export.zip`). Layout lives in `app/sermon_export.py`, apart from storage, like `app/pdf.py` for plans.
- **Connections**: a to-do step can go onto the prayer list (its `prayer_id` is kept on the step), "Also in your cave" shows those prayers, journal entries on the note's passages and other sermons on the same books (`GET /me/sermons/{id}/connected`, each part failing to empty on its own), and "Ask Aquila about this sermon" puts the main passage first and quotes the notes as the person's own words, so they can never become a citation.

### Church (`app/churches.py`, `app/church_web.py`, `web/church.js`)

The Church tab (`#church`, nav label "Church", a phone tab between Aquila and Cave) holds three parts in one segmented bar: Churches, Sermons (the sermon notes above) and Listen. Run `supabase/migrations/20261114_churches.sql` once, after the others; until then the tab says what to run, and drafting sermon notes from a link needs it too (it adds `church_id`, `source_url` and `week` to `sermon_notes`).
- **Personal, never social.** A church row belongs to the one person who added it. No following, no counts of who else goes, no directory, nothing suggested, and no giving (a church's page has About, not Give). Keep it that way.
- **Adding a church**: paste a link or enter it by hand. `POST /me/churches/read` reads the page plus up to three likely pages (visit, events, news), its schema.org data and its links, and the model fills `ChurchDraft` from the page text only. Nothing is saved until the person reviews the form and adds it. A church added from a site is read again in the background when it's opened a week or more after `checked_at`; that refresh only replaces events and notices, never gatherings the person may have corrected.
- **Every fetch goes through `church_web.safe_get`**, which follows http(s) to public addresses only, re-checks every redirect hop and caps the size. Never fetch a pasted link any other way.
- **Times**: gatherings are stored in the church's own IANA time zone, `{label, day (0 = Sunday), time "HH:MM"}`, and `church.js::nextAt` shows each in the person's time. Each event and gathering has a bell (Reminders below); an event's bell also offers its own calendar as an .ics file.
- **Notices and the info icon**: each notice keeps when Adullum first saw it (`added`); the icon's count is the notices newer than `notices_seen_at`, cleared by `POST /me/churches/{id}/seen` when the icon or the News tab is opened.
- **Live**: a church's YouTube `/live` page is checked at most every two minutes per channel (no API key: the canonical watch link plus `"isLiveNow":true`). Home shows one notification line (`cave.js::homeNote`) only while a church is live and its "Tell me when it's live" is on, and nothing else about churches; the same switch sends a notification once per stream (see Reminders below). `#church/live/<id>` plays it with notes beside it, kept in the browser until "Save to Sermons".
- **Sermons and Listen** come from each church's public YouTube feed (the channel id is found and kept on save) and podcast feed (Apple Podcasts links resolve to their feed; Spotify has none). Listen (`app/listen.py`) offers those sermons and Adullum's catalog, a short hand-chosen list of official public sermon podcasts across the traditions (`listen.py::CATALOG`, each feed checked to open and parse; keep it balanced across traditions if you add to it). Each sermon is tagged with seasons (weary, anxious, grateful, grieving, deciding, joyful) by the model once, kept in `sermon_moods`, which holds no personal data; one batch is tagged before the answer and the rest after it (`pending`, and the page looks again). The season and the source (everywhere, your churches or one of them, the catalog or one source) are two compact dropdowns on one line, with what Listen is behind the info button; keep pills off this page. Videos play in a docked youtube-nocookie player.
- **Notes from a link** (`POST /me/sermons/from-link`): the video's transcript (youtube-transcript-api, which YouTube often refuses to cloud servers) or else its description, drafted into `SermonDraft`. `churches.py::note_from_draft` keeps only passages the reference parser accepts, as verse blocks (text read from the database when shown), drops a "quote" that is really a verse, and adds timestamps only when there's a video. The draft is an ordinary sermon note after that.
- **The week after** (`#church/week/<id>`, `week_steps`): reread the main passage, carry a verse (Save puts it in Saved), one question (the answer kept in `week`), do the thing (the note's first to-do), pray. The Churches part shows it as "This week" for a sermon from the last eight days.

### Reminders and push notifications (`app/reminders.py`, `app/push.py`, `web/notify.js`, `web/sw.js`)

Run `supabase/migrations/20261115_reminders.sql` once, after the churches one. Set `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY` (from `scripts/make_vapid_keys.py`), `VAPID_SUBJECT` (a `mailto:`) and `CRON_SECRET`; left empty, `/push/key` returns null, the bell says notifications aren't set up, and nothing is ever sent.
- **Bells**: an event can remind a day or an hour before (the evening before or that morning when it has no time); a gathering reminds 30 minutes or an hour before, every week. One row per thing in `reminders`, keyed by what it's about, so the same bell changes it rather than adding another. A weekly one keeps its rule (`repeat`: day, time, zone, before) and `next_occurrence` works out each week in the church's own zone, so a clock change never shifts it.
- **Turning notifications on** only ever happens from a tap (`Notify.enable`): permission, then `sw.js` is registered and the browser's subscription goes to `POST /me/push`. iPhones allow web notifications only for a Home Screen app, so `web/manifest.json` and the icons in `web/icons/` exist for that, and there the first tap explains how. Signing out removes this device (`Notify.forget`), so a shared phone never gets the last person's reminders.
- **Sending**: Render's free plan sleeps, so two things send and either is enough: `reminders.loop` (started from `main.py`'s lifespan) every minute while awake, live checks every few minutes, and `.github/workflows/reminders.yml` every five minutes calling `POST /internal/send-reminders` with `CRON_SECRET` (needs the `DEPLOY_URL` and `CRON_SECRET` repo secrets). A reminder is claimed (`sent_at` set only if empty) before it's sent, so nothing goes twice; one more than six hours late is dropped. A device the push service says is gone (404/410) is deleted.
- **A notification only opens a page in Adullum** (`inside_link`: a `#...` route), and `sw.js` checks again before navigating. Keep both.

### Reflections (`app/reflections.py`, `web/reflections.js`)

A guided time with God over a stretch of time, in the Journal. Run `supabase/migrations/20261113_reflections.sql` once, after the others; until then the Journal works as before and starting a reflection says what to run.
- **Any length, any time.** New entry in the Journal is a small menu (`cave.js::newEntryMenu`): a journal entry or a reflection. A reflection looks back on a month, a quarter, a year or a season with the person's own dates, and ahead to the stretch after it. `reflections.py::period_for` picks the stretch that's ending (one just begun gives way to the one before), the start sheet's arrows move it, and `season_period` follows a season with one as long. There is no invitation or prompt to start one; keep it that way. The person can name it as they choose the stretch (`title`) and rename it at the top of the reflection; without a name it's called by its dates.
- **Three stages, saved as they write** (`PUT /me/reflections/{id}`, a second after each change). Look back: a summary folded into one line until it's tapped (the numbers they choose to count, cave counts with a flame from `cave_counts` and their own; their goals, from Pebbles and their own; passages; answered prayers as "stones of help"), then the areas of life they pick (Spiritual, Family and so on, or their own), each rated Hard, Mixed, Steady or Thriving with a line on what happened. Lay down. Look ahead mirrors look back: numbers to aim for with last time beside each, and for each area where they'd like it to be and what they'd like to see (a habit, a number, a date, or a hope). A month asks fewer questions.
- **Kept, it's the plan for the stretch ahead.** `POST /me/reflections/{id}/keep` turns each goal marked to track, and each of the person's own numbers to aim for, into a pebble (`refuge_seeds`, the id kept on the goal so it's never planted twice). The current plan is pinned at the top of the Journal (`reflections.js::planCard`, progress from `plan_progress`), the home screen shows a halfway check-in for two weeks from the middle of any stretch longer than a month (`reflection_glance`, `reflections.js::homeCard`), and the next reflection opens with "What you set out": that plan beside what happened.
- **The verse is a reference only**, its text read from the database. A reference that doesn't parse yet is kept as typed and named in `verse_error`, so it never costs the person the rest of their writing. The word for the year is UI text (Inter), not Scripture.
- **Private, and never memory.** Nothing here reaches `user_memories` or the Amens wall, and every query filters by `user_id` in code.

### Connections, the knowledge graph (`app/connections.py`, `web/graph.js`)

On screen it is "Connections" (it was "Map" at first, which read as a geographic map). The nav item, the door on the Bible's front page and the verse bar all use that name. On phones the tab bar holds Church instead, so the Bible's front page is its way in.

`GET /connections` draws two kinds of link from each seed verse, and every edge says which in `kinds`:
- **Close in meaning** (`"meaning"`, solid lines): the seed's stored embedding (read from the search translation's copy of that verse) fed back through `match_verses` for its nearest neighbours in other chapters. No new SQL and no LLM call.
- **Classic cross-references** (`"cross_ref"`, dashed accent lines): the seed's best-voted rows in `cross_references` (`supabase/migrations/20261111_cross_references.sql`, loaded by `scripts/ingest_cross_references.py`). The data is OpenBible.info's, CC BY, built on the public-domain Treasury of Scripture Knowledge; the licence asks for credit, which the graph's legend and the cross-reference panel give, so keep it. A link to a run of verses is drawn to its first verse and carries the run as `passage`. Until the migration runs the table is simply skipped.
A pair that is both is drawn solid in the accent colour. The legend toggles each kind.

Opened with nothing to show (the nav item, the Bible's door), the graph offers `graph.js::STARTERS`, a few themes each with the passage that starts it; the labels are themes, never quoted verse text. On phones the graph stops above the tab bar, Connections is the lit tab while it's open, and tapping another tab or any route change closes it.

Tapping a line (or "Why?" beside a neighbour in a verse's panel) calls `POST /connections/explain`: `app/agent/nodes.py::explain_link` gives two or three sentences on how the two passages connect, from those two passages only (a reply naming any other verse is rewritten, then replaced by a plain sentence), cached per link with `lru_cache`. `web/graph.js` lazy-loads d3 from cdnjs the first time the graph opens.

### Web client (`web/index.html`, `web/cave.js`, `web/graph.js`, `web/app.css`)

Vanilla JS, no build step. `index.html` holds every view (welcome, sign in, home, the Bible, Aquila, Church, the cave, settings, the admin desk, signed out) as `<section data-view>` blocks, a small hash router, the chat stream and the voice call. `cave.js` owns everything personal (sessions, past conversations in the Aquila rail with rename and delete, the home, cave and settings screens, the plan builder, the journal sheet, the extras under each answer) and is reached as `window.Cave`; `index.html` exposes `window.AdullumApp` back to it.

Naming on screen: the conversation view is "Aquila" (route `#aquila`; the old `#ask` still lands there), and the reader is "Bible" (`#bible`). The personal space is "the cave" (nav label "Cave"), with three tabs side by side: Journal (filtered by the person's own tags, or to Reflections; the old "season" picker is gone, and a season saved before shows as a tag; each entry's actions are one row, the likely next step in words, then Connections and Edit as icons and Share and Delete in the "⋯" menu, `cave.js::journalCard`), Refuge and Prayers (sermon notes moved to the Church tab). `cave.js` draws the cave and hands each tab its panel; Prayers by `prayers.js` (`window.Prayers`) and Refuge by `refuge.js` (`window.Refuge`). List filters are one compact line (`cave.js::listBar` with a `filterSelect` dropdown), never a row of pills. Notes, highlights, saved things and reading plans live in the Bible: "My notes" and "Saved" in the reader bar open `#bible/notes` and `#bible/saved`, and "Reading plans" on the Bible's front page opens `#bible/plans` (all through `reader.js::showMine`; the Saved page is drawn by `saved.js`, `window.Saved`, and the plans page by `cave.js::renderPlans`, which also holds the plan builder the home card uses), each with a way back to the open chapter. Past conversations live with Aquila, in the rail (or the Conversations sheet on a phone), where they can be opened, renamed and deleted. "What Aquila remembers" lives in Settings, next to profile and theme. Routes: `#cave`, `#journal`, `#prayers` and `#refuge` open the cave (all but the first on that tab); `#church` is the Church tab, with `#church/sermons`, `#church/listen`, `#church/add`, `#church/c/<id>`, `#church/live/<id>` and `#church/week/<id>` inside it, and `#sermons` lands on its Sermons; `#reflection/<id>` opens a reflection inside the Journal tab; `#sermon/<token>` is a shared sermon note, open to guests; `#amens` and `#pebbles` open Refuge inside that room; `#notes`, `#saved` and `#plans` land on those pages in the Bible (the old `#memorize` lands on Saved); `#conversations` lands on Aquila; `#settings` and `#remembers` open Settings (the second scrolled to memory); `#declare` is Declare and `#declare/<id>` a kept declaration; `#desk` is the admin desk.

Words: keep screens light to read. A title's explanation goes behind a small info button beside it, not in a paragraph under it: `cave.js::titleInfo` (or `info`, `sheetTitle` for a sheet, `room(title, about)` in Refuge, and `data-info="..."` on a static heading in `index.html`). The popover can carry a "Learn more" that opens a fuller explanation, as Amens does with "How Amens works". Keep on the page what has to be seen at once: safety and helplines, what sharing a link exposes, health cautions, empty states.

Type: Inter for the interface and Source Serif 4 only for quoted Scripture (`.scripture`, `.scripture-lg`), so a verse always reads as the text rather than as UI. Labels are sentence case; keep shouted uppercase kickers out.

Size: controls are compact and read their height from the tokens under the themes in `app.css` (`--h-btn`, `--h-btn-sm`, `--h-chip`, `--h-icon`), which grow a little on touch screens (`pointer: coarse`) so tap targets stay comfortable. Give a new button or chip one of those heights rather than a pixel value. Inputs stay at 16px so iOS doesn't zoom on focus. The cave tabs and the sign-in switch are segmented controls (`.tabs`, `.seg`); on a phone the cave's tabs share the full width, and sheets rise from the bottom. The top bar spans the window, and its gutter matches `.wrap` (20px, 16px on a phone) so the logo lines up with the page.

Shape: controls are pills (`--pill`), cards are generously rounded (`--radius`), and warmth comes from soft radial glows built from `--glow`/`--glow-strong` (the welcome preview, warm cards, sign in, signed out) plus the one gradient button, `.btn-ember`, which runs `--ember` into `--ember-hi` over an `--ember-glow` shadow. Build any new glow from those tokens so it follows the theme.

Themes: six palettes defined only as tokens at the top of `app.css` and set as `<html data-theme>`: Dawn, Olive Grove, Twilight and Hearth for everyone, and Almond (light) and Cedar (dark) for friends of the cave (`cave.js::SUPPORTER_THEMES`, unlocked by `cave.js::isFriend`, see Support below). The two supporter themes also switch on a signature layer the free ones leave off: a fixed aura behind the app (`--aura`, painted by `body::before`), gradient page titles (`--title-ink`), a richer gradient on primary buttons (`--ember-grad`, with a `--sheen` along the top), lifted cards (`--lift`, `--card-tint`), a glassier top bar (`--bar-glass`), a still picture behind the app (`--ornament` on `body::after`: Almond's flowering branch, Cedar's stars, grain and ridge of cedars, the ridge dropped on phones), a slow drift on the aura (`--aura-motion`, off under reduced motion), foil-edged feature cards (`--edge`), a gradient on the lit nav item (`--nav-active`), a gradient that slides on button hover (`--grad-size`) and their own text selection (`--select`). Keep ornaments to the corners and edges, never behind the reading column. Their defaults sit in a `:root` block above the themes, which must stay above them since the two tie on specificity. Give any new colour a token in all six blocks rather than a literal, and check its contrast in the light themes (Dawn, Olive Grove, Almond), where muted text and the accent are closest to failing.

Two things worth knowing before changing the SSE handling:
- It hand-rolls an SSE reader over `fetch()` because the browser's `EventSource` cannot send a POST body, and `/chat/stream` needs one.
- The server sends CRLF line endings; the client normalizes `\r\n` to `\n` before framing on blank lines. Removing that normalization silently breaks every response (the whole stream gets stuck in an internal buffer and nothing renders, with no error shown).

### Support Adullum (`app/support.py`, `web/support.js`)

Adullum stays free with no ads, and nobody's data is sold; giving pays the bills. `#support` is open to everyone and offers two links, set in `.env` as `SUPPORT_ONCE_URL` and `SUPPORT_MONTHLY_URL` (Stripe Payment Links) with `SUPPORT_MONTHLY_AMOUNT` as the page should say the price. Until they're set the page says giving opens soon, and its buttons are disabled rather than leading nowhere. The server never sees a card.
- **People are pointed there from wherever they'd see it**: "Support Adullum" in the account menu, a "Keep the fire lit" card at the end of the home screen's side column ("Not now" hides it on that device for 30 days, and supporters never see it), a card in Settings, a band and a footer link on the welcome page, and a line on the signed-out page.
- **Monthly givers are friends of the cave**: `profiles.supporter_since` (`supabase/migrations/20261112_supporters.sql`), set by `scripts/set_supporter.py` until a Stripe webhook does it. `PATCH /me` never accepts it. The checkout link carries the person's id as `client_reference_id` and their email as `prefilled_email`, so that webhook can find the account.
- **The thank-you is cosmetic only**: an ember on the account chip, "Friend of the cave" in the menu, and the Almond and Cedar themes. Admins (`ADMIN_EMAILS`) count as friends of the cave without giving (`cave.js::isFriend`): they get all of it and are never asked to give. `cave.js::supporterSince` stays the giving date alone, so an admin's thank-you line never names a month they started giving. Never hold back the Bible, Aquila, Refuge, prayers or anything else someone relies on, and never put ads in.

### Deployment

`render.yaml` defines the Render Blueprint; secrets are filled in on Render's dashboard, never committed. That includes `ADMIN_EMAILS` (who can open the admin desk); left empty, posts the automatic check isn't sure of wait with nobody to approve them. `AMENS_AUTO_APPROVE` (default true) lets posts the check is clear about go up straight away. `SUPPORT_ONCE_URL` and `SUPPORT_MONTHLY_URL` are the giving links; left empty, the Support page says giving opens soon. `.github/workflows/deploy-watch.yml` polls the Render API and the live `/health` endpoint, opening (or updating) a GitHub issue only on an actual build/deploy failure or a failing health check, and closing it on recovery, so a healthy deploy produces no noise.

## Product constraints that shape the code

- **Only public-domain translations** (KJV, WEB, ASV, BSB). Licensing a copyrighted translation needs a commercial agreement, not viable for an open repo.
- **Grounding is not optional.** `ground_check` exists because a hallucinated Bible verse is worse than a wrong answer in most other RAG use cases, it erodes trust in the whole app.
- **Denominationally disputed questions** (baptism mode, eschatology, predestination vs. free will) get the range of Christian interpretation, never one tradition's view asserted as the answer. This is a rule inside `SYNTHESIZE_SYSTEM_PROMPT` in `app/agent/nodes.py`, not a separate node, keep it there if you touch that prompt.

## House style: keep Aquila, and this repo, sounding like a person

Aquila's whole purpose is to feel like a warm, present companion, not a script. Never use an em dash, and avoid other stylistic tells that read as obviously AI-generated (the triplet "it's not X, it's Y" construction, excessive hedging, restating the question back before answering it). This applies to:
- Aquila's actual answers: `SYNTHESIZE_SYSTEM_PROMPT` and `META_SYSTEM_PROMPT` in `app/agent/nodes.py` carry this instruction directly, keep it there if you rewrite either prompt.
- Anything Claude Code writes in this repo: commit messages, code comments, this file. Use a comma, a period, or just a new sentence instead of an em dash.
