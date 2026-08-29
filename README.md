# Adullum

I built Aquila, a Bible study companion who answers Scripture questions with real
chapter-and-verse citations, never an invented reference. Ask her a question and
she looks up actual verses before she answers, so if the text doesn't address
something, she says so instead of making it up.

**[Try it live →](https://adullum.onrender.com)** (free-tier hosting, so the first
request after a while can take ~50 seconds to wake up; after that it's fast)

## What it does

- **Grounded answers, always cited.** Every claim traces back to a specific verse
  Aquila actually retrieved, checked by a separate verification step before it
  ever reaches you.
- **A real conversation, not a Q&A form.** Ask a follow-up, ask something totally
  different, it all threads together in one chat.
- **Knows the difference between "answer this" and "talk to me."** Ask her name
  or make small talk and she just answers, no scripture forced into it.
- **Handles book-level questions.** "Give me a starting point for studying James"
  grounds on that book's own opening verses instead of drifting across the whole
  Bible.
- **Reachable from more than one place.** The same agent answers the web chat
  below and, over [MCP](https://modelcontextprotocol.io), a Cognigy AI Agent.
  One brain, multiple front doors.

## Try it out

Open **[adullum.onrender.com](https://adullum.onrender.com)** and ask something.
A few to start with:

- "What does Romans 8:28 mean?"
- "How should I make sense of suffering as a Christian?"
- "What's your name?"
- "Give me a starting point for studying the Book of James."

## Architecture

```
                        ┌─────────────────────┐
   web chat ──────────▶ │   FastAPI            │  /chat, /chat/stream (SSE)
   Cognigy AI Agent ──▶ │   app/main.py        │  /mcp/sse (MCP server)
                        └──────────┬───────────┘
                                   │
                                   ▼
                        ┌─────────────────────┐
                        │  LangGraph agent     │  app/agent/graph.py
                        │  classify → retrieve │
                        │  → synthesize →      │
                        │  ground_check → cite │
                        └──────────┬───────────┘
                                   │
                                   ▼
                        ┌─────────────────────┐
                        │      Supabase        │
                        │  Postgres + pgvector │  verses, embeddings
                        └─────────────────────┘
```

Every request, from any front door, runs the same graph, one place Aquila's
behavior is defined, whether she's answering a browser or a Cognigy agent.

**Why Supabase for everything:** one Postgres instance holds the Bible corpus
(verses + embeddings via pgvector), auth for a future mobile app, and chat
history, no separate vector DB to sync. `supabase/schema.sql` is the full
schema plus the `match_verses` SQL function used for vector similarity search.

**Observability:** every request is traced in Langfuse (session, tags, model,
tokens, cost, and a "grounded" score on the verification step). See
`app/observability.py` for the SDK v4 gotchas that took real debugging to
find.

**Deployment:** one Render service serves the API, the MCP endpoint, and the
web chat together (`render.yaml`). A GitHub Actions workflow polls the deploy
and health check, opening a GitHub issue only if something actually breaks.

## Run it yourself

1. Create a free Supabase project, then in the SQL editor run `supabase/schema.sql`.
2. Copy `.env.example` to `.env` and fill in `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`,
   and an embedding/chat provider key (`OPENAI_API_KEY` by default).
3. Get a **public-domain** translation as JSON/CSV (KJV, WEB, ASV, or BSB;
   avoid NIV/ESV/NASB, which are copyrighted). See `scripts/ingest.py` for the
   expected input shape.
4. Install deps and ingest:
   ```bash
   pip install -e .
   python scripts/ingest.py --file data/bsb.json --translation BSB
   ```
5. Run it:
   ```bash
   uvicorn app.main:app --reload
   ```
6. Open `http://localhost:8000` for the chat UI, or POST to `/chat` with
   `{"query": "What does Romans 8:28 mean?"}`.

## Roadmap

- [x] RAG over verse-level chunks with hybrid retrieval (vector + reference + keyword)
- [x] LangGraph agent with a grounding/verification step
- [x] MCP server so external agents (Cognigy) can call Aquila as a tool
- [x] Langfuse tracing across every surface (web, MCP)
- [x] Deployed, with failure-only alerting on build/health issues
- [ ] Cognigy Voice Gateway, so this becomes an actual phone call
- [ ] Supabase Auth-backed user accounts, saved studies, chat history
- [ ] React Native / Expo mobile client against the same FastAPI service
- [ ] Eval set tracking citation accuracy over time

## Design notes worth remembering

- **Only public-domain translations.** Licensing copyrighted translations
  requires a commercial agreement, not viable for an open GitHub project.
- **Grounding is not optional.** The `ground_check` node exists specifically
  because a hallucinated Bible verse is worse than a wrong answer to most
  other RAG use cases; it erodes trust in the whole app.
- **Denominationally disputed questions** (baptism mode, eschatology, etc.)
  get a "here's the range of Christian interpretation" answer, not a single
  tradition's view asserted as definitive. This is a system-prompt rule in
  `app/agent/nodes.py::SYNTHESIZE_SYSTEM_PROMPT`.
