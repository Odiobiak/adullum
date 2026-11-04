# Aquila xApp Features: Cognigy Build Reference

Live version of this page: see the "Aquila xApp Catalogue" artifact (ask for it by name to redeploy). This file is the source of truth; the artifact is generated from it.

Project: **Aquila** (`6a9275fc643b16c54c336bd1`), Flow: **Aquila Flow** (`6a9275fd643b16c54c336eaf`), AI Agent Job node `6a9275fddf81fe67d0e6b5d8`.
Endpoints: `Aquila Webchat` (webchat3, xApp-capable), `Aquila Voice (WebRTC)` (voiceGateway2, no visual surface), `Aquila REST Endpoint` (rest).

## How to read this doc

Every feature carries a status and a "where it gets built" tag, because that decides who can do it and how:

| Tag | Meaning |
|---|---|
| **BUILT** | live in the Aquila flow today |
| **PLANNED** | designed here, buildable through `create_tool` + `manage_flow_nodes` with no manual step |
| **NEEDS GUI** | the logic is buildable through the tooling, but one resource (a Connection, Endpoint setting, Transformer, Handover Provider) only the Cognigy GUI can create |
| **BACKEND** | needs a change in the Adullum repo (FastAPI/LangGraph) before the Cognigy side can be wired |
| **EMBED** | a change to the embed snippet or `web/index.html`, not to Cognigy |
| **SUGGESTED** | worth having, not yet designed in detail |
| **DEFERRED** | parked by decision |

Build mechanisms, in order of preference:
1. **Tool on the Aquila AI Agent** (`create_tool` → `manage_flow_nodes`). LLM-invoked, lives under the one AI Agent Job. This is what the tooling can build end to end.
2. **Endpoint setting** in Cognigy GUI: **Deploy → Endpoints → Aquila Webchat**. Most Webchat v3 features live here.
3. **Embed option** in `initWebchat(configUrl, { settings, ... })`, which overrides the endpoint setting for that page.
4. **Adullum change**: a new field on `ChatResponse`, a new route in `app/main.py`, or a new MCP tool in `app/mcp_server.py`.

## The shape of every xApp tool

Every xApp tool follows the same chain: gated on `input.channel === "webchat3"` so a voice call can never hang on a `waitForInput` node it has no way to submit, with a plain-text fallback on the `else` branch for voice/REST:

```
tool node
  -> code node (build data)
  -> ifThenElse (input.channel === "webchat3")
       then: initAppSession -> show node (waitForInput, storeResultInContext) -> code node (build LLM-facing result)
       else: code node (plain-text fallback result)
  -> Resolve Tool Action (toolResponseValue: {{input.result}})
```

Two hard rules from the xApp node reference:
- `initAppSession` runs before any other xApp node in the tool branch. It populates `input.apps.url` and `input.apps.baseUrl`.
- Submitted data comes back on `input.data._cognigy._app.payload`, and on `context.<contextKey>` when the show node has `waitForInput` + `storeResultInContext`. Never treat it as trusted: anything a user can type or tap inside an xApp is client-controlled.

Which surface to use, in order of cost:

| Need | Use | Why |
|---|---|---|
| 2 to 5 fixed choices | `say` node with quick replies or Text with Buttons | No xApp session, renders inline, works everywhere Webchat does |
| One or more rich cards, no input | `say` node with Gallery / List / inline Adaptive Card | Still inline, still no session |
| A form, a picker, or anything that must block the flow until answered | `showXAppAdaptiveCard` | Declarative, sanitised, no JS to maintain |
| Loops, custom rendering, canvas, scrolling documents | `showXAppHtml` | Adaptive Cards cannot loop or scroll a long document |
| Something the user does on another device (voice caller) | `getXAppSessionPin` + SMS | The only way to hand a voice caller a screen |

---

# Part 1. xApp features for the study surface

## 1. Verse of the Day: BUILT

**Status:** live (tool node `6aa19dd5516224b0b91eccad`).

Shows an interactive card with today's featured verse and a "Study this with Aquila" action.

- `Pick Today's Verse` (code): picks a verse from a small curated public-domain (KJV) list, deterministic by day-of-year, into `context.votdVerse`.
- `showXAppAdaptiveCard`: renders `context.votdVerse.reference` / `.text` with two `Action.Submit` buttons (`study` / `dismiss`), `waitForInput: true`, `contextKey: "votd"`.
- `Build Result` (code): if the user tapped "Study this", the tool result tells the LLM to call `ask_aquila` next with that reference. The LLM chains the two tool calls itself.
- Voice/REST fallback: plain text "Today's verse is X: '...'".

**To extend:** replace the hardcoded list with a Supabase-backed pick (see Supabase Query Tool in Part 4) so it draws from the full ingested corpus instead of about 14 curated verses.

## 2. Follow-up Picker: BUILT

**Status:** live (tool node `6aa19dd7a238c05aa85f10a5`, named `show_followups`).

Takes the follow-up questions `ask_aquila` already returns (`followups: string[]` on `ChatResponse` in `app/schemas.py`) and renders them as tappable buttons.

- Tool parameter: `questions: string[]`. The LLM passes ask_aquila's own follow-ups back verbatim.
- `Build Follow-up Buttons` (code): loops over `input.aiAgent.toolArgs.questions` (Adaptive Cards can't loop, so this is `showXAppHtml`), builds one `<button onclick="SDK.submit({ followup: '...' })">` per question with HTML/JS escaping, into `context.followupHtml`.
- `showXAppHtml` (`mode: "body"`, `body: "{{context.followupHtml}}"`, `waitForInput: true`, `contextKey: "followupChoice"`).
- `Build Result` (code): tells the LLM to call `ask_aquila` again with the picked question.
- Voice/REST fallback: joins the questions into one sentence.

**Cheaper alternative worth testing:** three follow-ups fit in a `say` node with quick replies, with no xApp session at all. Keep the xApp version for when there are more than five, or when the follow-ups need grouping.

## 3. Passage Reader: BACKEND then PLANNED

Read a whole chapter (or a range) in a scrollable, well-set page instead of a chat bubble. The answer's `## The passage` section quotes a few verses; this opens the surrounding chapter.

**Node chain:**
```
tool: read_passage { reference, translation? }
  -> httpRequest GET {ADULLUM}/passage?ref=John+3&translation=BSB  (new Adullum route)
  -> code: build HTML (verse numbers as small caps, paragraph breaks, current verse highlighted)
  -> ifThenElse channel
       then: initAppSession -> showXAppHtml (mode: "full", screenTitle: reference, showCloseIcon: true) waitForInput: false
       else: say the first 3 verses and offer to continue
```

**How to add it:**
1. Adullum: add `GET /passage` in `app/main.py` that reuses `parse_reference` from `app/retrieval.py` and returns `{reference, translation, verses: [{n, text}]}`. Read-only, no LLM call, so it is cheap and cacheable.
2. Cognigy: `create_tool` with `toolType: "http"` pointed at that route (no secret needed if the route stays public and read-only).
3. `manage_flow_nodes`: the chain above. `waitForInput: false` because reading is not a decision; the conversation continues underneath.
4. Instruction for the agent job: "When the user asks to read a chapter or see the whole passage, call `read_passage`."

## 4. Translation Comparison: BACKEND then PLANNED

Show one verse in all four ingested public-domain translations (KJV, WEB, ASV, BSB) side by side. This is the feature only a multi-translation corpus can offer, so it is worth surfacing.

**Node chain:**
```
tool: compare_translations { reference }
  -> httpRequest GET {ADULLUM}/passage?ref=...&translation=KJV,WEB,ASV,BSB
  -> code: build a 4-column (stacks to 1 on mobile) HTML table, differing words marked
  -> showXAppHtml (mode: "full", screenTitle: "Compare")
```

**How to add it:** depends on #3's route accepting a comma-separated translation list. Check `supabase/schema.sql` for whether the `verses` table carries a `translation` column the query can filter on (the ingest script takes `--translation`, so it should). Fallback on voice: read the verse in two translations and stop.

## 5. Answer Feedback to Langfuse: BACKEND then PLANNED

A thumbs up/down with an optional comment after an answer, written as a Langfuse score on the exact trace that produced it. Grounding is the product promise; this is how you measure it from the user's side.

**Node chain:**
```
tool: rate_answer { trace_id }
  -> showXAppAdaptiveCard (two Action.Submit: helpful / not_helpful, Input.Text comment) contextKey "rating"
  -> httpRequest POST {ADULLUM}/feedback { trace_id, score, comment }
  -> Resolve Tool Action ("Thanks, noted")
```

**How to add it:**
1. Adullum: expose the trace id. `app/observability.py` already keeps `last_trace_id` on the per-request handler; add `trace_id: str | None` to `ChatResponse` and to the `ask_aquila` MCP tool's result, then add `POST /feedback` that calls Langfuse `score` with that id. Do not use the ambient trace context (the module docstring explains why).
2. Cognigy: tool as above. The agent job instruction should say to offer `rate_answer` only after an `ask_aquila` answer, never unprompted.
3. Alternative with zero xApp work: turn on **Conversation Rating** in the Webchat endpoint (Part 3, #5). That rates the conversation in Cognigy Insights, not the trace in Langfuse. Both can coexist.

## 6. Voice-to-Screen Handoff: NEEDS GUI

A voice caller asks for something visual (a reading plan, a comparison). Aquila Voice has no screen, so hand them one: generate a session PIN, text them the PIN page link, and continue the call while they open it.

**Node chain:**
```
inside any xApp tool's else branch (channel !== "webchat3"), when input.channel is voice:
  -> initAppSession
  -> getXAppSessionPin            (input.apps.session.pin, valid 5 minutes)
  -> ifThenElse (VG caller number present)
       then: Send SMS (Twilio) to caller: "{{input.apps.baseUrl}} and your PIN is {{input.apps.session.pin}}"
             -> say "I've texted you a link, open it and tell me when you're in"
             -> the show node runs as normal with waitForInput
       else: say the PIN and the short URL aloud, slowly, twice
```

**How to add it:**
1. GUI: install the Twilio extension (Manage → Extensions) and create a Twilio Connection (account SID + token) so the key is encrypted, not in a plaintext field.
2. `manage_flow_nodes`: `getXAppSessionPin` has no config. The Send SMS node comes from the extension, so it needs the GUI or the extension's node type once installed.
3. The PIN expires in 5 minutes. Say so on the call, and re-issue on request rather than failing silently.
4. On WebRTC (browser) calls the "caller number" is not a phone number. Fall back to reading the URL and PIN aloud.

## 7. Year Plan Builder, a live co-fill form: BACKEND BUILT, then PLANNED

Supersedes the earlier "Reading Plan Builder" sketch below with the actual feature: a full-year Bible reading plan, collected through a form that fills itself in as the user talks (voice or chat), while staying open the whole time for the user to edit directly. On completion it produces a plan card with a PDF download and an "email me this plan" option.

This is an enterprise-shaped pattern (a live-updating intake form beside a transcript, closable, dual-input) worth knowing well since it generalizes directly to a real business intake xApp, an insurance quote form being the reference case that motivated it.

**The mechanism that makes "fills in while you talk" possible:** `api.setAppState(templateId, data)`, callable from a Code node in the Flow. It pushes a fresh render into an **already-open** xApp session, no blocking, no dedicated node per update. The xApp shell page holds a live WebSocket connection to Cognigy's session manager specifically to receive these pushes, which is what lets an open form page update in place while the conversation keeps going underneath it.

**One correction worth remembering:** Cognigy's built-in xApp Overlay is not a split view. It replaces the whole Webchat widget with one full-screen panel, the same way the Home screen or Chat Options screen work, one screen at a time. Genuine side by side (transcript and form visible together) is not a stock Webchat v3 capability, it has to be built as a two-pane page: one pane holds the chat, the other is an iframe pointed at the xApp session's own URL (`input.apps.url`), kept open for the life of the conversation. Adullum's own `web/index.html` (not just a bare Cognigy embed) is the natural place to build this, since it already has a custom layout rather than only the stock widget.

**Node chain:**
```
tool: build_year_plan { start_date?, days?, translation? }
  -> initAppSession
  -> code: httpRequest POST {ADULLUM}/plan with whatever fields are already known
     -> Adullum generates the schedule + a one-time written overview, stores it, returns plan_id
  -> code: api.setAppState("generic-html", { html: <form pre-filled with known fields> })
     (waitForInput: false, the conversation is not paused)
  -> [ongoing, every turn]: a Code node merges any newly mentioned field into context.planForm,
     re-renders the HTML, and calls api.setAppState again with the updated form
  -> [any time]: the user can also type directly into the open form and submit;
     that arrives as input.data._cognigy._app.payload on whatever turn comes next,
     merging into the same context.planForm
  -> once required fields are complete: httpRequest POST {ADULLUM}/plan (final, with all fields)
     -> showXAppHtml/showXAppAdaptiveCard, waitForInput: true. The finished plan card,
        with a download link to {ADULLUM}/plan/{plan_id}/pdf and an "email me this plan" action
```

**How to build it:**
1. **Adullum backend, already built:**
   - `app/plan.py::generate_schedule(start_date, days)`. Pure, deterministic, no LLM call. Splits the 1189 chapters of the 66-book canon across `days` as evenly as possible, straight through in canonical order (Genesis to Revelation). Covered by `tests/test_plan.py`.
   - `app/plan.py::generate_overview(start_date, days, translation)`, the one LLM call the whole plan gets, a two-sentence written introduction, not a per-day call.
   - `app/pdf.py::render_plan_pdf(plan)`, renders the stored plan as a real paginated PDF via `reportlab` (a new dependency, added to `pyproject.toml`). Table cells use `Paragraph` objects so a long reading list wraps instead of clipping.
   - `POST /plan`, `GET /plan/{plan_id}`, `GET /plan/{plan_id}/pdf` in `app/main.py`. The PDF route renders on demand from the stored row rather than storing a file, so the same URL serves both the xApp's download button and the link a `send_email` tool puts in the email.
   - `reading_plans` table in `supabase/schema.sql`. No `user_id`/RLS yet, same as the `verses` table: nothing ties a plan to an identity until Aquila has one (Part 2, Identity and SSO). A plan is only reachable by its own generated id, never listed.
2. **Cognigy, still to build:** the `build_year_plan` tool and its Code nodes, following the chain above. The field-merge-and-re-render step relies on the agent job's instructions telling the LLM to update the form whenever it learns something, the same tool-calling discipline `verse_of_the_day` and `show_followups` already use, just called silently and repeatedly instead of once.
3. **Adullum website change:** a two-pane layout in `web/index.html`, chat on one side, an iframe on `input.apps.url` on the other. A plain client-side toggle button hides or shows the iframe pane, since closing the form doesn't need the Flow to know about it, the silent `setAppState` calls into a closed pane are harmless.
4. **Delivery:** the finished-plan card's download button links straight to `{ADULLUM}/plan/{plan_id}/pdf`. "Email me this plan" is a `send_email` tool whose body includes that same link, no attachment handling needed and no new Adullum route.
5. **Voice:** since a call has no screen, reuse Voice-to-Screen Handoff (#6 below): a session PIN texted to the caller, opened on any device, updating live while the call continues.

**Note:** the bidirectional part needs one small rule: track which fields the user touched directly (typed into the form themselves) and never let the agent's silent re-render overwrite one of those. A simple per-field "touched" flag in `context.planForm` is enough. Also worth a small spike before building the full chain: confirm an already-open xApp shell page actually repaints on a second `setAppState` call without a manual reload, the docs describe the transport for this but a two-minute prototype is cheaper than an assumption.

### Original sketch, superseded above

The first pass at this idea assumed a single blocking intake card and one `ask_aquila` call per day, both replaced by the live co-fill design once the actual requirement (fills in while you talk, PDF or email delivery) was clear:
```
tool: build_reading_plan { book_or_theme, days }
  -> initAppSession
  -> showXAppAdaptiveCard (intake) waitForInput
  -> loop calling ask_aquila once per day, collecting {day, reference, summary}
  -> showXAppHtml rendering the plan as a scrollable list
```
N sequential `ask_aquila` calls for a 365-day plan was always going to be too slow and too expensive, which is exactly why `generate_schedule` is deterministic instead.

## 8. Bookmarks and Notes: NEEDS GUI, then PLANNED

"Save this verse" with an optional note, listed later on a "My notes" screen. The first feature that needs a real user identity and a write to Supabase.

**Node chain:**
```
tool: save_note { reference, note? }
  -> ifThenElse (context.userId set, context.consent === true)
       then: httpRequest POST supabase /rest/v1/notes { user_id, reference, note }  (via encrypted Connection)
       else: call collect_consent (#12) first, or explain why it can't save
tool: show_notes
  -> httpRequest GET supabase /rest/v1/notes?user_id=eq.{{context.userId}}
  -> code: HTML list with "Study this" per row -> showXAppHtml
```

**How to add it:** blocked on the Supabase Connection (Part 4) and on an identity that is not client-supplied (Part 2, #1). Add a `notes` table and RLS policy in `supabase/schema.sql` first.

## 9. Memory Verse Practice: SUGGESTED

Progressive reveal: show the reference, hide the text, let the user type it, then show a diff. Pure Cognigy, no backend.

- `showXAppAdaptiveCard` with `Input.Text` (multiline) and one `Action.Submit`.
- Code node compares the submission to the verse text (normalise case and punctuation), builds a second card with matched words in bold.
- Reuse the Verse of the Day pick, or take a reference as the tool parameter.

## 10. Study Session Booking: SUGGESTED

Book time with a study leader. The bundled `appointment-booking.card.json` template returns `{appointmentDate, appointmentTime, service, notes, action: "book"}`. Confirm via the `send_email` tool type. Fits inside the intake wizard (#11) once that exists.

## 11. Multi-Step Intake Wizard: PLANNED

Prayer request or study-group signup: several screens gated on prior answers, reusing one `initAppSession`.

**Node chain:**
```
tool: collect_intake
  -> initAppSession (once)
  -> showXAppAdaptiveCard step 1 (contextKey "step1") -> code (validate/branch)
  -> showXAppAdaptiveCard step 2 (contextKey "step2", conditional on step1) -> code (validate/branch)
  -> ... -> confirmation screen summarising all context.step*
```

**Build notes:**
- Map the full step graph before building.
- Validate in a code node between screens. Re-show the same card with an error rather than accepting bad input.
- Decide the persistence target (Supabase row, `send_email`, or session-only) before building the last screen.
- **Abandon-mid-flow, answered:** the show nodes' Webchat v3 overlay settings include `showCloseIcon` and `sendEventOnCloseIconClick`. Turn both on, and the flow gets an event when the user closes the overlay, so it can resume the conversation instead of waiting forever. Set `closeOnSubmit: true` on the last step.

## 12. Consent and Privacy Opt-in: PLANNED (compliance)

One Adaptive Card asking permission before anything personal is stored (notes, plans, profile). Writes `context.consent = true` plus a timestamp, and is checked by every tool that persists.

- Pair with the Webchat **Privacy Notice** screen (Part 3, #6), which covers the endpoint-level notice. This card covers the specific act of saving.
- If Contact Profiles are on (Part 2, #6), also write the consent flag into the profile so it survives the session.

## 13. Study Material Upload: DEFERRED

Upload a sermon outline or notes PDF and ask Aquila about it. Two routes:
- The bundled `document-upload.html` template submits files as base64 (about 5 MB cap). Adullum would need a route to receive and chunk them.
- Webchat **Attachment Upload** needs a File Storage Connection (Azure Blob, S3, or GCS) in the endpoint. Cognigy virus-scans on upload.
Deferred because it changes the product: Aquila answers from Scripture, and a user document is a second, ungrounded source. Decide that first.

## 14. RBAC-Driven Rendering: BACKEND then NEEDS GUI

Same `ask_aquila` answer, richer rendering for a "study leader" role (retrieval path, `ground_check` verdict, trace id) than for everyone else.

**Node chain:**
```
after ask_aquila resolves
  -> ifThenElse on context.role (from a trusted claim, NEVER from client-submitted xApp data)
       then (leader): initAppSession -> showXAppHtml (answer + debug panel)
       else: plain say, no xApp
```

**How to add it:**
1. Adullum: add an optional `debug` block to `ChatResponse` and the MCP tool result (retrieval path used, ground_check verdict and retry count, trace id). Check what `app/agent/state.py` tracks today; not all of it is exposed.
2. Identity: the role must arrive through the Endpoint Transformer (Part 2, #1) into `input.data`, then be copied into `context.role` once. Never read it from `SDK.submit` payloads.
3. Test both branches with `talk_to_agent` once the LLM connection is fixed.

## 15. Live Ops Dashboard: BACKEND then PLANNED

Internal view of ingestion and groundedness health as an xApp.

**Node chain:**
```
tool: show_ops_dashboard (gate behind the same role check as #14)
  -> httpRequest(s): translation/verse counts (Supabase), retry rate / groundedness (Langfuse API)
  -> code: shape JSON
  -> initAppSession -> showXAppHtml (mode: "full", counters, optional refresh via SDK.submit)
```

**Build notes:** needs a read-only aggregation route in Adullum (or direct Langfuse API calls). Decide refresh cadence before wiring a refresh button.

---

# Part 2. Enterprise features

## 1. Identity and SSO: EMBED + NEEDS GUI

Who is talking to Aquila, in a way the flow can trust.

- **Untrusted but useful:** the embed snippet accepts `userId` and `sessionId` options (see Cognigy's Webchat `embedding.md` on GitHub). Set `userId` from the host page's logged-in user so Contact Profiles and Previous Conversations line up. Anyone can edit their own page, so this is identity for continuity, not for authorisation.
- **Trusted:** pass a short-lived JWT from the host page (in `data` on the first message, or an embed option), and verify it in the endpoint's **Input Transformer** (GUI: Deploy → Endpoints → Aquila Webchat → Transformer Functions). The transformer sets `userId` and puts verified claims (`role`, `tenant`) on `input.data`. Transformers are GUI-only; the tooling used here cannot author them.
- Adullum side: nothing until a feature needs the identity (#8, #14 in Part 1).

## 2. Role-Based Access: depends on #1

Store the verified role in `context.role` once per session (extend `bootstrap_session`), and gate tools on it in an `ifThenElse` at the top of each restricted tool's branch. Also tell the agent job which tools are leader-only, so the LLM does not offer them to everyone.

## 3. Handover to a Human: NEEDS GUI

"Talk to a pastor" or "talk to a study leader": escalate the conversation to a human queue with the transcript attached.

- Providers available in Cognigy: **NiCE CXone** (Integrated, if the installation is platform-integrated, otherwise Non-Integrated with Tenant ID, Business Unit ID and API credentials), **Salesforce MIAW** (not the legacy Chat/LiveAgent, retired Feb 2026), Genesys Cloud Open Messaging, 8x8, Chatwoot, RingCentral Engage, Storm.
- GUI: Build → Handover Providers → + New. Then add a **Handover to Human Agent** node in the tool that should escalate. Add **Set Handover Inactivity** and **Close Handover** nodes for hygiene.
- Extras: Real-time Queue Notifications and User Inactivity Detection are documented handover features; turn them on once the provider exists.
- Deferred for Salesforce (no org). NiCE CXone is the natural fit for this account if a test business unit exists.

## 4. Data Protection Settings: NEEDS GUI

Endpoint → **Data Protection & Analytics**. Turn on, and record the decision:
- **Mask Sensitive Analytics** and **Mask Sensitive Logging** (replace `inputText`, `inputData`, `userId`, `text`, `data` with asterisks in Insights and Logs).
- **Mask IP Address**.
- **Enable Input Sanitization** (server-side removal of harmful HTML from user input, before it reaches any code node or xApp).
- **Hide References to External Resources in Transcripts**.
- Decide **Collect Conversations** and **Contact Profiles** deliberately; both store personal data.
- For finer control, a Code node can edit `analyticsdata` before it is written (e.g. `delete analyticsdata.data.token`).

## 5. xApp Security: PLANNED (convention)

- Every string interpolated into `showXAppHtml` must be HTML-escaped and JS-escaped in the code node that builds it. This includes LLM output and `ask_aquila` answers, not just user input. The Follow-up Picker already does this; copy its escaping helper.
- Prefer `showXAppAdaptiveCard` where possible. Cards are data, not markup.
- In the embed, set `widgetSettings.customAllowedHtmlTags` to the minimum the answers need (`p`, `strong`, `em`, `h2`, `ul`, `li`, `a`, `blockquote`).
- Cognigy's own page on this: xApps → Security → Secure xApp from XSS.

## 6. Contact Profiles and Previous Conversations: NEEDS GUI

Turn on **Contact Profiles** (endpoint) so `bootstrap_session` has something to read, and **Previous Conversations** (Webchat Home Screen setting) so a returning user sees their history. Both depend on a stable `userId` (#1). Document retention.

## 7. Audit Log: SUGGESTED

One structured who/what/when row per sensitive action (save note, escalate, delete conversation). Cheapest version: a code node that appends to `analyticsdata`, visible in Insights. Durable version: a Supabase `audit_log` table via the Supabase Query Tool.

## 8. Rate Limit and Abuse Guard: SUGGESTED

A per-session counter in `context` incremented by each tool's first code node; when it passes a cap, the tool resolves with "let's slow down" instead of calling Adullum. Protects the Render instance and the OpenAI quota from a runaway loop.

## 9. Locale and Language: NEEDS GUI

- Turn on **Collect Metadata** in the Webchat endpoint. The first message then carries `data._webchat3Metadata.language`, `platform`, `browser`. Copy `language` into `context.locale` in `bootstrap_session`.
- Endpoint → **Real-time Translation Settings** can translate the whole conversation. Be careful: Aquila's answers quote Scripture verbatim from a public-domain English translation, and machine-translating a verse breaks the grounding promise. If translation goes on, keep the `## The passage` block untranslated (or offer a translation in the user's language only where one is ingested).
- **RTL support** is built into Webchat v3. Relevant the day Aquila shows Hebrew or Aramaic terms.

## 10. Business Hours, Maintenance, Session Expiry: NEEDS GUI / EMBED

- **Business Hours** (Webchat Behavior settings): show a message outside hours. Useful if handover (#3) is staffed.
- **Maintenance** mode in the embed (`maintenance: { enabled, mode: "hide" | "disable" | "inform", title, text }`, needs `embeddingConfiguration.awaitEndpointConfig: true`). Use it during Adullum deploys that `deploy-watch.yml` flags as failing.
- Endpoint → **Session Management** sets session expiry. Long enough for a slow reading, short enough that `context` (consent, role) does not outlive the person.

## 11. Analytics and Insights: NEEDS GUI

**Collect Analytics** on the endpoint, plus the **Request Rating** node (or Webchat Conversation Rating) to get ratings into Insights. Langfuse stays the source for groundedness; Insights covers conversation volume, drop-off, and ratings. The OData endpoint exports both for a BI tool.

## 12. Proactive Messages: Inject and Notify: NEEDS GUI

Push a message into a running session (`/inject`) or to a user (`/notify`) from outside the flow, e.g. "your reading plan for today". Available on endpoints that support it; check the Inject & Notify section of the endpoint. Needs a caller (a scheduled job in Adullum, or a Render cron) and the endpoint URL token stored as a secret.

## 13. Tenant Feature Flags: SUGGESTED

A small per-tenant config (Supabase row or a Lookup node keyed on `input.data.tenant` from #1) that toggles which tools are active, so one agent can serve several groups or churches with different feature sets.

## 14. Health Check Tool: SUGGESTED

One tool that hits Adullum `/health`, the Supabase REST root, and the MCP `/mcp/sse` handshake and reports which are up. Belongs on the Ops Dashboard (Part 1, #15) and on every onboarding checklist.

## 15. Packaging and Environments: SUGGESTED

`manage_packages` exports the LLM connection plus tools as a package, so a staging project or a second tenant starts from an import. Pair with a naming convention (`aquila-<env>`) and keep secrets out of the package (Connections export by reference).

## 16. Custom Extension: SUGGESTED

For JWT/HMAC-signed calls a Code node cannot do cleanly, or for a custom xApp node with full control over rendering (the docs have an Extension SDK template for exactly that). Installed once, reused everywhere.

---

# Part 3. Webchat inclusion: what to turn on in Aquila Webchat

The Adullum page (`web/index.html`) currently runs its own chat client against `/chat/stream`, plus Cognigy's click-to-call widget for voice. xApps only render in a Webchat v3 surface, so to use any of Part 1 on the Adullum site the Cognigy widget has to be embedded there too.

## 1. Embed Webchat v3 on the Adullum page: EMBED

1. GUI: Deploy → Endpoints → Aquila Webchat → **Embedding HTML**, copy the snippet.
2. Pin a version instead of `releases/latest` (e.g. `releases/download/v3.x.y/webchat.js`), so a Webchat release cannot change the page under you.
3. Paste before `</body>` in `web/index.html`, next to the existing click-to-call script, with settings that match the ink-and-brass theme:
```html
<script src="https://github.com/Cognigy/Webchat/releases/download/v3.x.y/webchat.js"></script>
<script>
  initWebchat("https://endpoint-trial-us.cognigy.ai/<CONFIG_URL_TOKEN>", {
    settings: {
      colors: { primaryColor: "#8a6d3f" },
      behavior: { enableTypingIndicator: true, enableSTT: false },
      embeddingConfiguration: { awaitEndpointConfig: true },
      widgetSettings: { customAllowedHtmlTags: ["p","strong","em","h2","h3","ul","ol","li","a","blockquote","br"] }
    }
  });
</script>
```
4. Decide the relationship with the hand-rolled client: keep both (custom client for the journal feel, widget for xApps), or move fully to the widget and keep `/chat/stream` for the MCP/REST path. Keeping both means two ways to talk to Aquila on one page; label them.
5. Alternative for the future mobile app: the **npm package** embed (`@cognigy/webchat`) instead of the hosted script.

## 2. Home Screen and Conversation Starters: NEEDS GUI

Enable Home Screen, welcome text in Aquila's voice ("Ask about a passage, or let me pick a verse for today"), and starters of type **Postback Value** mapped to tools: `verse of the day`, `start a reading plan`, `compare translations`. Background colour: paper `#f6f2e9`.

## 3. Teaser Message: NEEDS GUI

A single line on the closed widget ("A verse for today?") with one or two starters. Quiet, not a pop-up.

## 4. Previous Conversations: NEEDS GUI

Home Screen → Previous Conversations. Needs a stable `userId` (Part 2, #1) to be meaningful.

## 5. Chat Options screen: NEEDS GUI

Turn on: **Quick Replies** (e.g. "Read the chapter", "Something to sit with"), **Conversation Rating** (Always), **Delete Conversation** (a privacy affordance), **Footer** (link to the privacy policy). **Text-to-Speech**: off by default, since the voice endpoint already exists for that.

## 6. Privacy Notice: NEEDS GUI

Notice screen shown before the first message: title, text, link to the policy, accept button. This is the endpoint-level notice; the consent card (Part 1, #12) covers saving specific data.

## 7. Persistent Menu: NEEDS GUI

Three entries that always work: Verse of the day, Start over, Talk to a person (when #3 in Part 2 exists).

## 8. xApp Overlay settings: PLANNED (per show node)

Set on every `showXAppAdaptiveCard` / `showXAppHtml`: `autoOpen: true` (open in the chat, not a new tab), `screenTitle` (the reference or the task), `showCloseIcon: true`, `sendEventOnCloseIconClick: true` (so the flow hears an abandon), `closeOnSubmit: true`, `feedbackMessage` ("Saved" / "Got it"). Keep these values identical across tools by convention, since there is no shared branding flow (Part 4).

## 9. Inline rich messages instead of xApps: PLANNED

For anything that does not need to block: **Gallery** of verse cards, **List** for a plan overview, **Text with Buttons** for two or three choices, inline **Adaptive Cards**. All are `say` node payloads, no session, and they also degrade gracefully on REST.

## 10. Date Picker: NEEDS GUI (Say node setting)

Webchat v3 date picker for the reading-plan start date, or "remind me on". Lighter than an xApp for one date.

## 11. Attachment Upload: NEEDS GUI, DEFERRED

Webchat Behavior → Attachment Upload, needs a File Storage Connection (Azure Blob, S3, GCS; private bucket, Cognigy virus-scans). Tied to Part 1, #13's product decision.

## 12. Behavior: typing indicator, message delay, STT, unread badge: NEEDS GUI / EMBED

`enableTypingIndicator: true`; `messageDelay` small (Aquila streams a study, not chat quips); `enableSTT` off on the page (voice has its own widget; also unsupported on Firefox); **Unread Messages** badge on.

## 13. Collect Metadata: NEEDS GUI

One toggle; feeds locale (Part 2, #9) and device-aware rendering (stack translation columns on `platform: "mobile"`).

## 14. Style Presets, Colors, Icon, Watermark: NEEDS GUI

Pick a preset, then override colours to ink `#1a1712`, paper `#f6f2e9`, brass `#8a6d3f`. Upload an icon. Watermark setting under Advanced.

## 15. Webchat Plugins: SUGGESTED

A custom message plugin (hosted JS) could render `ask_aquila`'s four headings as ruled sections inside the widget, the way `web/index.html::renderAnswerHtml` does today. Needs hosting for the plugin file and a `<script>` in the embed. Only worth it if the widget replaces the custom client.

## 16. Accessibility and RTL: convention

Webchat v3 is WCAG 2.2 AA. Keep it that way in xApps: `aria-label` on Adaptive Card inputs, transcripts for any audio, contrast checked against paper and ink in both themes. RTL is built in; relevant for Hebrew terms.

---

# Part 4. Reusable infrastructure (build once, use everywhere)

### Correction: no "Execute Flow" node available through the tooling

Earlier drafts assumed an **Execute Flow** node (call another flow, then return) as the reuse mechanism. Checked directly against the tooling used to build this project: the only cross-flow node it supports is **`goTo`**, which redirects and does **not** return. There is also no tool here to create a bare (non-AI-Agent) Flow or a Webhook Endpoint; both are GUI-only (`Build > Flows`, `Deploy > Endpoints`). So "reusable" here means "a tool on the Aquila AI Agent", the same pattern as `verse_of_the_day`. The GUI's node palette does have Execute Flow; if someone builds a shared flow by hand, the tooling can still `goTo` into it.

| Component | Mechanism | Status |
|---|---|---|
| Session bootstrap | tool `bootstrap_session`, runs once per session | **BUILT** (node `6aa2dd53516224b0b92110a2`): pulls `profile.name`/`profile.email` into context, sets `context.bootstrapped`. Extend with `context.locale`, `context.role`, `context.consent` |
| ID&V | tool, same shape | not started; depends on Part 2, #1 |
| Auth/Login | tool, sets `context.accessToken`/`context.userId` | not started |
| Generic API-caller template | `httpRequest` + pre/post-process code nodes, duplicated per integration | not started |
| Supabase query tool | API-caller template pointed at Adullum's Supabase | **scaffolding only**, blocked on an encrypted Connection (below) |
| Salesforce / CXone handover | native handover node + provider | **deferred** (no org); CXone worth a test unit |
| xApp init/branding | copy-paste convention across tools (same `initAppSession` and overlay values) | by convention, not a component |
| Error/fallback | already centralised in the AI Agent Job node's `errorHandling` config | nothing to build |
| Custom Extension | real Cognigy Extension | not started |
| Package export | `manage_packages` | not started |
| Webhook Router | dedicated Flow + Webhook Endpoint, both GUI-only; I can fill in the dispatcher once the shell exists | blocked on the shell |

### Note on the Webhook Endpoint

A Webhook Endpoint is bound to one Flow, accepts `{userId, sessionId, text, data}`, and delivers the result to a callback URL set once in the Endpoint config. For a router serving different callers, have the dispatcher read a `callbackUrl` from the incoming `data` and `httpRequest`-POST the result there instead.

### Note on the Supabase Connection

The `create_tool`/`manage_flow_nodes` API does **not** expose Cognigy's encrypted Connection object; only the GUI's "+ New Connection" (on an HTTP Request node's Authentication section, or Build → Connections) creates one. Putting the Supabase **service role key** into a tool's plain `headers` field would store it in plaintext in the flow config, visible to anyone with edit access and exportable via Packages. Create the Connection in the GUI, then hand over its reference ID. Supabase expects a header literally named `apikey`; check the outgoing request in the Interaction Panel's Debug Mode after wiring.

### Known blocker

The Aquila AI Agent's LLM connection (Azure OpenAI `gpt-4.1-mini`, connection `88e50803-f24b-4048-a83f-cc754192f766`) was failing on every turn at the time of writing, confirmed independent of anything built here (tested with the new tools deleted; Adullum's `/chat` and `/mcp/sse` work when hit directly). Until it is fixed, nothing in Parts 1 to 3 can be tested end to end. Check the connection's key validity and quota.

---

# Suggested build order

1. Fix the LLM connection (blocker for all testing).
2. Webchat inclusion, GUI pass: Part 3 #2, #3, #5, #6, #7, #12, #13, #14, and Part 2 #4. One afternoon, no code.
3. Embed the widget on the Adullum page (Part 3 #1) and confirm Verse of the Day and Follow-up Picker render in the overlay.
4. Overlay settings and XSS convention across the two built tools (Part 3 #8, Part 2 #5).
5. Passage Reader route in Adullum, then the tool (Part 1 #3). Translation Comparison rides on it (#4).
6. Trace id on `ChatResponse`, `/feedback` route, then Answer Feedback (Part 1 #5).
7. Supabase Connection in the GUI, then Consent card, then Bookmarks and Notes (Part 1 #12, #8).
8. Identity via Transformer (Part 2 #1), then RBAC rendering and Ops Dashboard (Part 1 #14, #15).
9. Voice-to-Screen once Twilio exists (Part 1 #6).
10. Handover provider when there is a human to hand to (Part 2 #3).
