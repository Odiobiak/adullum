# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Adullum is a Bible study agent named Aquila: ask a Scripture question, get a grounded answer with chapter-and-verse citations, never an invented reference. Built as a learning project (LangGraph + Supabase + FastAPI) designed to grow: chat today, voice and mobile later.

## Commands

```bash
pip install -e ".[dev]"                                  # install app + dev deps
uvicorn app.main:app --reload                             # one process: REST API, SSE, MCP server, and the web UI all at :8000
python scripts/ingest.py --file data/bsb.json --translation BSB   # load a translation into Supabase (see --help for --batch-size)
pytest                                                    # run the test suite (tests/)
```

Config lives in `.env`, read once into `app/config.py::settings`. `tests/conftest.py` sets dummy Supabase/OpenAI credentials so the suite runs without a real `.env` (in CI, in particular); the suite itself only covers pure logic (`app/retrieval.py`'s parsers, `app/schemas.py`, the graph's routing functions) and the API contract with the compiled `agent` mocked out in `tests/test_api.py` — nothing in it makes a real LLM or Supabase call. `.github/workflows/test.yml` runs it on every push and PR.

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

### Observability (`app/observability.py`)

Langfuse SDK v4. The module docstring documents three non-obvious failure modes already hit and fixed once, read it before touching this file:
- `os.environ` must actually have `LANGFUSE_*` set (pydantic-settings reads `.env` into its own object without touching `os.environ`; the Langfuse SDK reads `os.environ` directly). `load_dotenv()` in `app/config.py` handles this.
- The per-request `CallbackHandler` must never be cached or shared across requests. It exposes the trace it created via the plain instance attribute `last_trace_id`, and sharing one instance would race that attribute across concurrent requests.
- Scoring a trace from inside a node function must use that explicit `last_trace_id`, not Langfuse's ambient "current trace" context. LangGraph runs sync node functions on a worker thread that does not inherit the main coroutine's contextvars, so the ambient lookup fails there.

### My Cave: accounts, journal, memory (`app/auth.py`, `app/cave.py`, `app/memory.py`, `web/cave.js`)

Run `supabase/migrations/20261104_my_cave.sql` once in the Supabase SQL editor before any of this works; until then `/me/*` returns a 503 that says so, and chat quietly runs as a guest.
- **Auth is brokered by this server.** The browser never holds a Supabase key. `/auth/*` signs people in on a throwaway client from `app/auth.py::_auth_client` (never the shared `get_supabase()` one, which a sign-in would switch to that user's token), using the implicit flow so magic-link tokens land in the URL fragment for `web/cave.js` to pick up. Magic links only return here if the site URL is listed under Supabase Auth > URL Configuration.
- **Every `/me` query filters by `user_id` in code**, because the service-role client bypasses RLS. The RLS policies in the migration exist for a future client talking to Supabase directly.
- **Memory is never Scripture.** `app/memory.py::recall` hands the graph `memories` for signed-in people; `synthesize`, `answer_meta` and `ground_check` all label them as notes about the person that can't support a claim about the Bible. Keep that labelling if you touch those prompts. Note-taking (`remember_turn`) runs after the answer is delivered and is non-fatal, like `suggest_followups`.

### Knowledge graph (`app/connections.py`, `web/graph.js`)

`GET /connections` feeds each seed verse's stored embedding back through `match_verses` to find its nearest neighbours in other chapters. No new SQL and no LLM call. `web/graph.js` lazy-loads d3 from cdnjs the first time the graph opens.

### Web client (`web/index.html`)

Single-file vanilla JS chat client, no build step. Two things worth knowing before changing the SSE handling:
- It hand-rolls an SSE reader over `fetch()` because the browser's `EventSource` cannot send a POST body, and `/chat/stream` needs one.
- The server sends CRLF line endings; the client normalizes `\r\n` to `\n` before framing on blank lines. Removing that normalization silently breaks every response (the whole stream gets stuck in an internal buffer and nothing renders, with no error shown).

### Deployment

`render.yaml` defines the Render Blueprint; secrets are filled in on Render's dashboard, never committed. `.github/workflows/deploy-watch.yml` polls the Render API and the live `/health` endpoint, opening (or updating) a GitHub issue only on an actual build/deploy failure or a failing health check, and closing it on recovery, so a healthy deploy produces no noise.

## Product constraints that shape the code

- **Only public-domain translations** (KJV, WEB, ASV, BSB). Licensing a copyrighted translation needs a commercial agreement, not viable for an open repo.
- **Grounding is not optional.** `ground_check` exists because a hallucinated Bible verse is worse than a wrong answer in most other RAG use cases, it erodes trust in the whole app.
- **Denominationally disputed questions** (baptism mode, eschatology, predestination vs. free will) get the range of Christian interpretation, never one tradition's view asserted as the answer. This is a rule inside `SYNTHESIZE_SYSTEM_PROMPT` in `app/agent/nodes.py`, not a separate node, keep it there if you touch that prompt.

## House style: keep Aquila, and this repo, sounding like a person

Aquila's whole purpose is to feel like a warm, present companion, not a script. Never use an em dash, and avoid other stylistic tells that read as obviously AI-generated (the triplet "it's not X, it's Y" construction, excessive hedging, restating the question back before answering it). This applies to:
- Aquila's actual answers: `SYNTHESIZE_SYSTEM_PROMPT` and `META_SYSTEM_PROMPT` in `app/agent/nodes.py` carry this instruction directly, keep it there if you rewrite either prompt.
- Anything Claude Code writes in this repo: commit messages, code comments, this file. Use a comma, a period, or just a new sentence instead of an em dash.
