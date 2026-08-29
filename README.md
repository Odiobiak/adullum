# Adullum

A Bible study agent: ask any question about Scripture, get a grounded answer with
chapter-and-verse citations. Built as a learning project (LangGraph + Supabase +
FastAPI) designed to grow — chat today, voice and mobile later.

## Architecture

```
                        ┌─────────────────────┐
   client (web/CLI) ──▶ │   FastAPI  /chat     │  (streams via SSE)
   voice STT/TTS ──▶    │   app/main.py        │
   mobile app ──▶       └──────────┬───────────┘
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
                        │  Postgres + pgvector │  verses, embeddings,
                        │  Auth + Storage      │  users, chat history
                        └─────────────────────┘
```

Why Supabase for everything: one Postgres instance holds the Bible corpus
(verses + embeddings via pgvector), auth for a future mobile app, and chat
history — no separate vector DB to sync. `supabase/schema.sql` is the full
schema plus the `match_verses` SQL function used for vector similarity search.

## Setup

1. Create a free Supabase project, then in the SQL editor run `supabase/schema.sql`.
2. Copy `.env.example` to `.env` and fill in `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`,
   and an embedding/chat provider key (`OPENAI_API_KEY` by default).
3. Get a **public-domain** translation as JSON/CSV (KJV, WEB, ASV, or BSB —
   avoid NIV/ESV/NASB, which are copyrighted). See `scripts/ingest.py` for the
   expected input shape.
4. Install deps and ingest:
   ```bash
   pip install -e .
   python scripts/ingest.py --file data/bsb.json --translation BSB
   ```
5. Run the API:
   ```bash
   uvicorn app.main:app --reload
   ```
6. POST to `/chat` with `{"query": "What does Romans 8:28 mean?"}`.

## Roadmap

- [x] RAG over verse-level chunks with hybrid retrieval (vector + reference + keyword)
- [x] LangGraph agent with a grounding/verification step
- [ ] Supabase Auth-backed user accounts, saved studies, chat history
- [ ] Streaming voice front-end (STT → `/chat` → TTS)
- [ ] React Native / Expo mobile client against the same FastAPI service
- [ ] Eval set (LangSmith/Langfuse) tracking citation accuracy over time

## Design notes worth remembering

- **Only public-domain translations.** Licensing copyrighted translations
  requires a commercial agreement — not viable for an open GitHub project.
- **Grounding is not optional.** The `ground_check` node exists specifically
  because a hallucinated Bible verse is worse than a wrong answer to most
  other RAG use cases — it erodes trust in the whole app.
- **Denominationally disputed questions** (baptism mode, eschatology, etc.)
  get a "here's the range of Christian interpretation" answer, not a single
  tradition's view asserted as definitive. This is a system-prompt rule in
  `app/agent/nodes.py::SYNTHESIZE_SYSTEM_PROMPT`.
