# Aquila's voice call in Refuge (Cognigy)

"Talk out loud" in Refuge (`web/refuge.js::talkRoom`) opens Cognigy's WebRTC
widget (`web/index.html::VOICE_CONFIG_URL`). Cognigy answers the call with an AI
Agent that listens like Refuge's Aquila and reaches back into Adullam over MCP
for Scripture.

```
Browser (Refuge) --WebRTC--> Cognigy Voice Gateway --> "aquila" endpoint
                                                         |
                                       Flow "Aquila Refuge Voice"
                                         Once: settings + greeting
                                         Afterwards: AI Agent job "Aquila"
                                           |  MCP over SSE, Bearer MCP_SECRET
                                           v
                              Adullam /mcp/sse (app/mcp_server.py)
                                find_verses   verses word for word, ~1s, no model
                                ask_aquila    the full study graph, ~10s
```

## Where things live

| What | Where |
|---|---|
| Tenant | `trial.cognigy.ai` (API `https://api-trial.cognigy.ai/new`) |
| Project | Adullam `6af5f866e509708910c132fe` |
| Endpoint | aquila `6af610eab18820d0e42a19d8`, `https://endpoint-trial.cognigy.ai/b9e2c1f6...` |
| AI Agent, flow, nodes | built by `scripts/build_cognigy_voice.py`; edit the words there, not in the editor |

## Rebuild

```bash
# .env: COGNIGY_API_URL, COGNIGY_API_KEY (Cognigy > My Profile > API Keys), MCP_SECRET
python scripts/build_cognigy_voice.py --project 6af5f866e509708910c132fe --endpoint 6af610eab18820d0e42a19d8
```

It updates the AI Agent in place, deletes and rebuilds the flow, and points
the endpoint at it. Safe to run as often as needed. On a new tenant, create a
project and a Voice Gateway endpoint first, then pass their ids.

## Why it's built this way

- **She listens first.** The agent's instructions mirror Refuge's `listen`
  node: a few spoken sentences, one gentle question at most, Scripture only
  when it's wanted.
- **She never quotes from memory.** Verses come from `find_verses`, read from
  the verses table, so a voice reply can only quote what's really there. It
  answers in about a second, which matters on a call; `ask_aquila` is kept for
  a real study question.
- **Nothing is remembered.** The AI Agent uses no contact profile, and the MCP
  tools run without Langfuse tracing, as Refuge promises.
- **Care comes first.** If someone may be in danger, she gives helplines and
  "Talk to a person", and never ends the call herself.
- **Gentle pacing.** The caller can talk over her (two words, so a "mm"
  doesn't), and after 20 quiet seconds she says she's still there, at most twice.

## Manual steps (the API can't do these)

1. **Voice Gateway.** The trial tenant shares Cognigy's own Voice Gateway
   (`api-vg-trial.cognigy.ai`), so calls connect without an account of your
   own, with Deepgram speech in English by default. An organisation account
   (an Account SID, linked with `POST /organisations/voicegateway/account`)
   is only needed for a phone number or your own speech credentials.
2. **A calmer voice (optional).** Deploy > Endpoints > aquila > Voice settings:
   text to speech Deepgram (connection `Aqu-voice`), speech to text Deepgram
   Flux (`Aqu-voice2`), English. Left unset, the system default voice speaks.
3. **Adullam.** `find_verses` must be live and `MCP_SECRET` set on Render to
   the value in `.env` (both done; `/mcp/sse` refuses a caller without it).
4. **Once it works:** turn off the MCP tool's debug messages ("Adullam
   Scripture" node) so the Interaction Panel stays quiet.

## Testing

- **By text, from code:** make a temporary REST endpoint on the flow, post
  turns to it, then delete it. The first turn is the call connecting (it
  greets); a verse request should show a tool call and quote `find_verses`'
  words exactly (check them against `GET /verse?ref=...`). Done on
  2026-11-14: greeting, a gentle reply, two BSB verses word for word, and
  goodbye ending in a hangup.
- **A real call from Refuge:** greeting, barge-in, a pause, a verse, "goodbye".

## If she says nothing

Every turn logging "Loading Flow" then "Finished" a few milliseconds later,
with no output, means a branch's nodes aren't reached. That happened once:
nodes put under the Once branches with "appendChild" are skipped at runtime,
so the call connected and stayed silent. `FlowBuilder` explains the rule.
