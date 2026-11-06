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
pytest                                                    # run the test suite (tests/)
```

Config lives in `.env`, read once into `app/config.py::settings`. `tests/conftest.py` sets dummy Supabase/OpenAI credentials so the suite runs without a real `.env` (in CI, in particular); the suite itself only covers pure logic (`app/retrieval.py`'s parsers, `app/schemas.py`, the graph's routing functions) and the API contract with the compiled `agent` mocked out in `tests/test_api.py`. Nothing in it makes a real LLM or Supabase call. `.github/workflows/test.yml` runs it on every push and PR.

## Always
When writing code, always write code like a good human software engineer. Always use the best coding practice and naming convention. Make sure the code is very well documenteted, readable and easy to follow.

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

`SYNTHESIZE_SYSTEM_PROMPT` asks for four Markdown headings (`## The passage`,
`## Context`, `## What it means`, `## To sit with`), which the web client renders
as ruled section headings and `suggest_followups` extends with a "Continue" block.
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

Run the files in `supabase/migrations/` once each, in date order, in the Supabase SQL editor (`20261104_my_cave.sql`, `20261105_hearth.sql`, `20261106_plan_titles.sql`, and on through `20261110_refuge.sql`). Until the first runs, `/me/*` returns a 503 that says so and chat quietly runs as a guest; until the second, the home screen hides its embers and "Mark as read" explains what to run; until the third, plans shaped with Aquila save without their title and show a generic one.
- **Auth is brokered by this server.** The browser never holds a Supabase key. `/auth/*` signs people in on a throwaway client from `app/auth.py::_auth_client` (never the shared `get_supabase()` one, which a sign-in would switch to that user's token), using the implicit flow so magic-link tokens land in the URL fragment for `web/cave.js` to pick up. Magic links only return here if the site URL is listed under Supabase Auth > URL Configuration.
- **Every `/me` query filters by `user_id` in code**, because the service-role client bypasses RLS. The RLS policies in the migration exist for a future client talking to Supabase directly.
- **The home screen is one request.** `GET /me/home` (`app/hearth.py`) gathers embers, the last conversation, today's plan reading, the prayer list at a glance, how many memory verses are due, a glance at the Amens wall, a journal entry to revisit and two memories (the screen doesn't show the memories; they live in Settings), each part failing to null on its own. Days are the browser's local days (it sends `today`, checked by `app/days.py::parse_today`), so a streak doesn't break at a UTC midnight.
- **Verse text on screen always comes from the database.** The verse of the day (`app/hearth.py::VERSES_OF_THE_DAY`), the welcome page's example passage and the signed-out page's verse are fetched through `/verse-of-the-day` and `/verse`, never typed into the page. The only hard-coded quotation is the KJV 1 Samuel 22 passage that explains the name, and it is labelled KJV.
- **Plans shaped with Aquila can't invent a chapter.** `POST /me/plans/build` asks the model only for books and chapter ranges (`app/plan.py::PlanDraft`). `expand_sections` resolves every book through `app/retrieval.py::canonical_book`, clamps ranges to `BOOK_CHAPTER_COUNTS`, and the split into days is the same arithmetic as the whole-Bible plan. Keep the model out of the day-by-day layout.
- **Memory is never Scripture.** `app/memory.py::recall` hands the graph `memories` for signed-in people; `synthesize`, `answer_meta` and `ground_check` all label them as notes about the person that can't support a claim about the Bible. Keep that labelling if you touch those prompts. Note-taking (`remember_turn`) runs after the answer is delivered and is non-fatal, like `suggest_followups`.

### Prayers and memory verses (`app/prayers.py`, `app/memorize.py`, `web/prayers.js`, `web/memorize.js`)

Run `supabase/migrations/20261109_prayers_highlights_memorize.sql` once, after the others. Until then those two tabs (and highlights) return a 503 that says what to run, and their home cards don't appear.
- **A prayer is open until it's marked answered**, with an optional line on how; it can be reopened. When memory is on, `prayers.py::_remember` keeps one memory note per prayer (`user_memories.prayer_id`, deleted with it, rewritten when it's answered or edited), so Aquila can bring an open request up. Same "never Scripture" labelling as every memory.
- **Memory verses are read from the verses table, never sent by the browser**, and capped at six verses. Practice shows the first letter of each word, then the verse; the person answers "Not yet", "Almost" or "Got it", and `memorize.py::next_review` (a cut-down SM-2) sets the next due date. Keep the schedule on the server, so every device agrees on what's due.

### Refuge and the admin desk (`app/refuge.py`, `app/one_another.py`, `app/care.py`, `web/refuge.js`)

A quiet room in the cave for every kind of season, not only hard ones. Run `supabase/migrations/20261110_refuge.sql` once, after the others; until then the tab shows the setup message. Five rooms, drawn in place inside the tab (not hash routes, so Leave quickly can replace the one history entry and Back never leads back in):
- **Write it out**: a blank page or a guided shape (lament, thanks, hoping). "Let it go" never touches the server; only "Keep it" stores anything (`refuge_writings`). "Plant it in Grow" turns a hope into a seed.
- **Talk with Aquila**: the graph's `listen` node through `POST /me/refuge/talk`. The browser holds the talk, and it vanishes when the person leaves Refuge (`Refuge.hide`, called by `cave.js` on any other tab or view) unless they press Keep (`refuge_talks`). These runs pass `callbacks: []`, so they are never traced to Langfuse, and nothing here reaches `user_memories`. Keep both true.
- **Grow**: hopes, goals (with steps), habits and prayers (tended day by day, shown as a week of dots, never as a streak count). `refuge_seeds` and `refuge_checkins`, local days via `parse_today`.
- **Be still**: one minute of breathing with Psalm 46:10, read from the database.
- **Amens** (first called "One another", which `app/one_another.py` and the `refuge_*` tables still say): share a burden or good news without a name. Saying amen is the one reaction (on a burden it means "I prayed", on good news "I'm rejoicing"), and a post's count is its amens. A post goes through `one_another.screen` (contact details refused; signs of risk are not posted and the writer is shown helplines; OpenAI moderation refuses hate, harassment, sexual and illicit content, while violence goes to a person since it also catches someone describing harm done to them), then waits as `pending` on the **admin desk** (`#desk`, `/admin/refuge`) until someone in `ADMIN_EMAILS` approves it. A report takes it off the wall at once and back to the desk. Others can only say amen, send one of `KIND_WORDS` (verses stored by reference and read from the database), or report. Nobody, the desk included, is ever sent who wrote a post; keep `user_id` out of every wall and desk select.

Helplines live in `web/refuge.js::HELPLINES`, chosen by the browser's region and changeable. Nothing anyone keeps or shares in Refuge appears on the home screen. The one exception is deliberate and public: the home's Amens card (`one_another.py::amens_glance`, drawn by `refuge.js::homeCard`) shows this week's amens across the whole wall and the newest post by someone else still waiting for this person's amen, with an Amen button. Never put the person's own posts, or anything that shows they posted, on that card.

### The Bible reader, notes and highlights (`app/bible.py`, `app/notes.py`, `app/highlights.py`, `web/reader.js`)

Anyone can read; notes, highlights and memorizing need an account. Run `supabase/migrations/20261107_verse_notes.sql` once, after the others (and `20261109_...` for highlights). Until then the reader works and saving returns a 503 that says what to run.
- **A translation is offered only once it's loaded.** `app/bible.py::TRANSLATIONS` lists the public-domain ones (BSB, KJV, WEB, ASV); `/bible/translations` returns the subset that has verses in the database, cached for five minutes, so after ingesting a new one the picker shows it within that window. To add one, fetch it with `scripts/fetch_translation.py` (which normalizes book names and the quirks of each source, listed in its docstring), ingest it, and it appears. It is stored as text only and borrows BSB's embeddings for vector search (see Retrieval above).
- **One translation preference drives everything.** The hidden `#translation` input in `index.html` is the single value Aquila, the verse of the day, Connections and the reader all read. `web/reader.js` sets it from the reader's picker and the one in Settings, remembers it on the device, and saves it to `profiles.preferred_translation` when signed in (applied on the next sign-in via the `adullum:profile` event `cave.js` dispatches).
- **Notes are pinned to book, chapter and verse range, not to a translation**, so a note shows beside the same verse whichever translation is open. `translation` and `verse_text` record what the person was reading when they wrote it. Every `/me/notes` query filters by `user_id`, same rule as the cave.
- **Highlights follow the same rule**, one colour per verse (gold, green, blue, rose), stored a row per verse so overlapping highlights never conflict. The server reads each verse's text from the verses table when it saves one, and `highlights.py::group_highlights` joins neighbouring verses of one colour back into a passage for My notes. The colours are `--hl-*` tokens in all four themes.
- **Asking Aquila about a verse or note is an ordinary question** composed by `reader.js::askQuery` with the reference first (`On John 3:16-18: ...`), so `parse_reference` pulls exactly those verses and nothing in the graph changes. A note goes in quoted as the person's own words; the synthesize prompt still grounds only on retrieved verses, so a note can't become a citation.
- Reader links are `#bible/<Book-with-hyphens>/<chapter>[/<verse>]`; `Reader.href("John 3:16")` builds one. "Read in context" under each answer and in the Connections side panel uses it.

### Connections, the knowledge graph (`app/connections.py`, `web/graph.js`)

On screen it is "Connections" (it was "Map" at first, which read as a geographic map). The nav item, the phone tab and the verse bar all use that name.

`GET /connections` feeds each seed verse's stored embedding (read from the search translation's copy of that verse) back through `match_verses` to find its nearest neighbours in other chapters. No new SQL and no LLM call. `web/graph.js` lazy-loads d3 from cdnjs the first time the graph opens.

### Web client (`web/index.html`, `web/cave.js`, `web/graph.js`, `web/app.css`)

Vanilla JS, no build step. `index.html` holds every view (welcome, sign in, home, the Bible, Aquila, the cave, settings, the admin desk, signed out) as `<section data-view>` blocks, a small hash router, the chat stream and the voice call. `cave.js` owns everything personal (sessions, past conversations in the Aquila rail with rename and delete, the home, cave and settings screens, the plan builder, the journal sheet, the extras under each answer) and is reached as `window.Cave`; `index.html` exposes `window.AdullumApp` back to it.

Naming on screen: the conversation view is "Aquila" (route `#aquila`; the old `#ask` still lands there), and the reader is "Bible" (`#bible`). The personal space is "the cave" (nav label "Cave"), with four tabs side by side: Journal (filtered by the person's own tags; the old "season" picker is gone, and a season saved before shows as a tag), Prayers, Refuge and Plans. `cave.js` draws the cave and hands each tab its panel; Prayers by `prayers.js` (`window.Prayers`) and Refuge by `refuge.js` (`window.Refuge`). List filters are one compact line (`cave.js::listBar` with a `filterSelect` dropdown), never a row of pills. Notes, highlights and verses to learn live in the Bible: "My notes" and "Memorize" in the reader bar open `#bible/notes` and `#bible/memorize` (`reader.js::showMine`; the Memorize page is drawn by `memorize.js`, `window.Memorize`), each with a way back to the open chapter. Past conversations live with Aquila, in the rail (or the Conversations sheet on a phone), where they can be opened, renamed and deleted. "What Aquila remembers" lives in Settings, next to profile and theme. Routes: `#cave`, `#journal`, `#prayers`, `#refuge` and `#plans` open the cave (all but the first on that tab); `#amens` opens Refuge inside the Amens room; `#notes` and `#memorize` land on those pages in the Bible; `#conversations` lands on Aquila; `#settings` and `#remembers` open Settings (the second scrolled to memory); `#desk` is the admin desk.

Type: Inter for the interface and Source Serif 4 only for quoted Scripture (`.scripture`, `.scripture-lg`), so a verse always reads as the text rather than as UI. Labels are sentence case; keep shouted uppercase kickers out.

Shape: controls are pills (`--pill`), cards are generously rounded (`--radius`), and warmth comes from soft radial glows built from `--glow`/`--glow-strong` (the welcome preview, warm cards, sign in, signed out) plus the one gradient button, `.btn-ember`, which runs `--ember` into `--ember-hi` over an `--ember-glow` shadow. Build any new glow from those tokens so it follows the theme.

Themes: four palettes (Dawn, Olive Grove, Twilight, Hearth) defined only as tokens at the top of `app.css` and set as `<html data-theme>`. Give any new colour a token in all four blocks rather than a literal, and check its contrast in the two light themes, where muted text and the accent are closest to failing.

Two things worth knowing before changing the SSE handling:
- It hand-rolls an SSE reader over `fetch()` because the browser's `EventSource` cannot send a POST body, and `/chat/stream` needs one.
- The server sends CRLF line endings; the client normalizes `\r\n` to `\n` before framing on blank lines. Removing that normalization silently breaks every response (the whole stream gets stuck in an internal buffer and nothing renders, with no error shown).

### Deployment

`render.yaml` defines the Render Blueprint; secrets are filled in on Render's dashboard, never committed. That includes `ADMIN_EMAILS` (who can open the admin desk); left empty, nobody can approve a post and the Amens wall stays empty. `.github/workflows/deploy-watch.yml` polls the Render API and the live `/health` endpoint, opening (or updating) a GitHub issue only on an actual build/deploy failure or a failing health check, and closing it on recovery, so a healthy deploy produces no noise.

## Product constraints that shape the code

- **Only public-domain translations** (KJV, WEB, ASV, BSB). Licensing a copyrighted translation needs a commercial agreement, not viable for an open repo.
- **Grounding is not optional.** `ground_check` exists because a hallucinated Bible verse is worse than a wrong answer in most other RAG use cases, it erodes trust in the whole app.
- **Denominationally disputed questions** (baptism mode, eschatology, predestination vs. free will) get the range of Christian interpretation, never one tradition's view asserted as the answer. This is a rule inside `SYNTHESIZE_SYSTEM_PROMPT` in `app/agent/nodes.py`, not a separate node, keep it there if you touch that prompt.

## House style: keep Aquila, and this repo, sounding like a person

Aquila's whole purpose is to feel like a warm, present companion, not a script. Never use an em dash, and avoid other stylistic tells that read as obviously AI-generated (the triplet "it's not X, it's Y" construction, excessive hedging, restating the question back before answering it). This applies to:
- Aquila's actual answers: `SYNTHESIZE_SYSTEM_PROMPT` and `META_SYSTEM_PROMPT` in `app/agent/nodes.py` carry this instruction directly, keep it there if you rewrite either prompt.
- Anything Claude Code writes in this repo: commit messages, code comments, this file. Use a comma, a period, or just a new sentence instead of an em dash.
