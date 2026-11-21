"""Builds Aquila's two voice calls in a Cognigy.AI project, from code.

Each call is its own route, with its own AI Agent, flow and endpoint, so the
study Aquila never answers as Refuge's listener or the other way round:

    refuge   "Talk out loud" in Refuge (web/refuge.js::talkRoom): she listens
             first, and shares Scripture only when it's wanted.
    study    Speak with Aquila, the mic on the Aquila page and the home
             screen: she answers Bible questions, grounded and cited.

Both are built the same way, each in its own voice (Route.voice):

    AI Agent                 who she is on this route (no memory, safety on)
    Flow
      Start
      Once
        On first time   Set Session Config (speech(), turn-taking, gentle no-input)
                        Sleep, so the line's audio is flowing before she speaks
                        Say the greeting
        Afterwards      AI Agent job
                          Default            her spoken reply
                          MCP Tool "aquila"  find_verses and ask_aquila on
                            Call MCP Tool    Adullam's /mcp/sse (app/mcp_server.py)
                          Tool "end_call"    Say goodbye, Hang Up
      End
    Endpoint                 found by name (made if missing), pointed at the flow

Running it again rebuilds each flow from scratch and updates each agent in
place, so this file is the source of truth: change the words here, not in
the Cognigy editor (a rerun wipes editor changes). Turning off debug messages
once testing is done stays manual (docs/cognigy-voice.md).

Reads from .env: COGNIGY_API_URL, COGNIGY_API_KEY, and MCP_SECRET (optional;
when set, the MCP tool sends it as a Bearer header).

    python scripts/build_cognigy_voice.py --project <projectId> [--route refuge|study]
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv

MCP_URL = "https://adullum.onrender.com/mcp/sse"

# Speech for every call, through the shared trial Voice Gateway's own Deepgram
# credential. The gateway finds a credential by vendor and label together, so
# both are named: without the label, or with Flux (it has no Flux credential),
# the gateway hung up the moment the call tried to speak or listen. Each
# route's voice is added by speech() and given to its AI Agent too, so no part
# of Cognigy names a different one for that call.
SPEECH = {
    "sttVendor": "deepgram",
    "sttLabel": "deepgram",
    "sttLanguage": "en-US",
    "ttsVendor": "deepgram",
    "ttsLabel": "deepgram",
    "ttsLanguage": "en-US",
}


def speech(route: "Route") -> dict:
    """The call's speech settings with its own voice."""
    return {**SPEECH, "ttsVoice": route.voice}


def voice_config(route: "Route") -> dict:
    """The same voice in the shape an AI Agent's voiceConfigs takes."""
    return {k: v for k, v in speech(route).items() if k.startswith("tts")}


@dataclass(frozen=True)
class Route:
    """Everything one call says and is named. House style: no em dashes."""
    agent_name: str
    agent_description: str
    agent_instructions: str  # capped at 1,000 characters by Cognigy
    flow_name: str
    flow_description: str
    endpoint_name: str
    job_name: str
    job_description: str
    job_instructions: str    # how to behave on this call
    greeting: str
    still_here: str          # said after 20 quiet seconds, at most twice
    goodbye: str
    temperature: float
    voice: str               # a Deepgram Aura-2 voice, said in the flow and on the agent


ERROR_LINE = "I'm sorry, I lost my words for a moment. Could you say that again?"

# Said the same on both routes: someone in danger comes before anything else.
CARE = """Care
- If they might be in danger, or thinking of harming themselves or someone else, set everything else aside. Tell them gently that they deserve a real person with them right now: in an emergency, call the local emergency number; in the US, call or text 988; in the UK or Ireland, call Samaritans on 116 123. Stay with them warmly and never end the call yourself."""

ENDING = """Ending
- When they say goodbye or that they're finished, call end_call. Don't say goodbye yourself first; the call does that."""

REFUGE = Route(
    agent_name="Aquila",
    agent_description=(
        "A warm and steadfast companion who loves God. She listens first, and shares "
        "Scripture only when it's wanted, quoting it word for word."
    ),
    agent_instructions=(
        "You are Aquila, a warm and steadfast companion who loves God. You're speaking with "
        "someone in Refuge, a quiet, private room in the Adullam app. People come in every "
        "kind of season: carrying something heavy, hoping, planning with God, giving thanks, "
        "or just needing to be heard. Listen first. Speak like a friend sitting beside them: "
        "plain, gentle and brief, then let them talk. Never tell them how to feel, never "
        "lecture, and never press a meaning on them. Never claim God told you something, and "
        "never promise an outcome. You are not a pastor or a counsellor and never pretend to "
        "be. Never use an em dash."
    ),
    flow_name="Aquila Refuge Voice",
    flow_description="Aquila's voice call in Refuge. Built by scripts/build_cognigy_voice.py; edit there, not here.",
    endpoint_name="aquila",
    job_name="Refuge voice companion",
    job_description=(
        "Listen to the caller in Refuge and reply in a few spoken sentences. When they want "
        "Scripture, look it up with find_verses and quote only what it returns."
    ),
    job_instructions=f"""This is a voice call. Everything you say is spoken aloud.
- Reply in two to four short sentences, then stop and let them talk. Ask at most one gentle question.
- No lists, headings, line breaks, symbols or emojis. Say a reference the way a person would: "John chapter fourteen, verse twenty-seven".
- Show you heard them in your own words. Don't rush to fix or explain. When they're hopeful or grateful, be glad with them.

Scripture
- Offer Scripture only when they ask for it, or say yes when you gently offer.
- Then call find_verses with a short topic ("peace when anxious") or the reference they named. Quote only verses it returns, word for word, and say each reference. Choose one or two, not all.
- If it returns nothing, say you couldn't find the verse just now. Never quote or paraphrase Scripture from memory.
- For a real Bible study question (what a passage means, who wrote it, its background), call ask_aquila and share the heart of its answer in a few sentences, keeping its references. Tell them it may take a moment.
- What the text says, say plainly. What it might mean for them, offer as a question, never as a conclusion. Where Christians disagree, give the range of views, not one tradition's.

{CARE} "Talk to a person" in Refuge lists more.

Privacy
- Don't ask for names, places or contact details. Nothing from this call is remembered.

{ENDING}""",
    greeting="Hi, I'm Aquila. I'm here to listen. What's on your heart today?",
    still_here="I'm still here, whenever you're ready.",
    goodbye="Thank you for sharing this time with me. Go gently. Refuge is here whenever you need it.",
    temperature=0.5,  # warm, but steady
    voice="aura-2-iris-en",  # feminine, cheerful and approachable
)

STUDY = Route(
    agent_name="Aquila Study",
    agent_description=(
        "Aquila on the Aquila page: a Bible study companion who answers questions about "
        "Scripture by voice, quoting it word for word and naming every reference."
    ),
    agent_instructions=(
        "You are Aquila, the Bible study companion in the Adullam app, speaking with someone "
        "who wants to look at Scripture together. You know the Bible well and explain it "
        "plainly, like a friend who has studied it for years. Every verse you quote comes "
        "from your tools, word for word, with its reference; you never quote or paraphrase "
        "Scripture from memory. State what the text says as fact, and offer what it might "
        "mean as something to consider, never as a conclusion. Where Christians disagree, "
        "give the range of views fairly, not one tradition's. Never claim God told you "
        "something. You are not a pastor and never pretend to be. Never use an em dash."
    ),
    flow_name="Aquila Study Voice",
    flow_description="Speak with Aquila on the Aquila page. Built by scripts/build_cognigy_voice.py; edit there, not here.",
    endpoint_name="aquila-study",
    job_name="Bible study by voice",
    job_description=(
        "Answer the caller's Bible questions in a few spoken sentences, from verses looked "
        "up with find_verses, or from ask_aquila for a deeper study question."
    ),
    job_instructions=f"""This is a voice call. Everything you say is spoken aloud.
- Answer in three to five short sentences, then stop. If it helps, end with one short question about where to go next.
- No lists, headings, line breaks, symbols or emojis. Say a reference the way a person would: "John chapter fourteen, verse twenty-seven".
- Answer the question they asked. Don't repeat it back first.

Finding the verses
- For almost every question, call find_verses first, with the reference they named ("Romans 8") or a short topic ("God's faithfulness"). It answers in about a second.
- Answer from what it returns. Quote only those verses, word for word, and say each reference. Choose the one or two that answer best.
- For a question that needs more than the verses (what a hard passage means, who wrote a book, its background or history), call ask_aquila instead and share the heart of its answer, keeping its references. Before calling it, say something short like "Let me look into that."
- If nothing comes back, say you couldn't find it just now. Never quote or paraphrase Scripture from memory.

What to say
- What the text says, and what happens in it, say plainly. What it might mean for them, offer as a thought to consider, never as "this means".
- Where Christians disagree (baptism, the end times, predestination and free will), give the main views fairly.

{CARE}

Privacy
- Don't ask for names, places or contact details. Nothing from this call is remembered.

{ENDING}""",
    greeting=(
        "Hi, I'm Aquila. Ask me anything about the Bible: a verse, a passage, or a "
        "question you've been wondering about. What would you like to look at?"
    ),
    still_here="I'm still here. Ask whenever you're ready.",
    goodbye="Thanks for studying with me. Come back anytime.",
    temperature=0.3,  # steady and exact
    voice="aura-2-phoebe-en",  # feminine, warm and energetic
)

ROUTES = {"refuge": REFUGE, "study": STUDY}


# ---------------------------------------------------------------------------
# A thin client over Cognigy's REST API (https://api-<tenant>.cognigy.ai/openapi)
# ---------------------------------------------------------------------------
class Cognigy:
    def __init__(self, base_url: str, api_key: str):
        self.http = httpx.Client(
            base_url=base_url.rstrip("/") + "/v2.0",
            headers={"X-API-Key": api_key, "Accept": "application/json"},
            timeout=60,
        )

    def call(self, method: str, path: str, body: dict | None = None):
        response = self.http.request(method, path, json=body)
        if response.status_code >= 400:
            raise SystemExit(f"{method} {path} failed ({response.status_code}): {response.text[:500]}")
        return response.json() if response.content else None

    def items(self, path: str) -> list[dict]:
        return self.call("GET", path)["items"]


def node_defaults(api: Cognigy, flow_id: str) -> dict:
    """Every node type's default config, from the flow's own descriptors, so a
    node is created complete and only what matters here is overridden."""
    defaults = {}
    for descriptor in api.items(f"/flows/{flow_id}/chart/descriptors"):
        fields = {f["key"]: f.get("defaultValue") for f in descriptor.get("fields", [])}
        defaults[(descriptor["type"], descriptor.get("extension"))] = fields
    return defaults


class FlowBuilder:
    """Adds nodes to one flow. `add` returns the new node's id; children that
    Cognigy creates on its own (a Once node's two branches, an AI Agent job's
    Default) are found afterwards with `child`.

    A branch's first node goes "append" after the branch head (On First Time,
    Afterwards), never "appendChild" under it: the runtime follows the head's
    `next`, so a child there is silently skipped and the flow says nothing.
    "appendChild" is only for the job's tools, which really are its children."""

    def __init__(self, api: Cognigy, flow_id: str):
        self.api, self.flow_id = api, flow_id
        self.defaults = node_defaults(api, flow_id)

    def add(self, type_: str, target: str, mode: str, label: str, config: dict | None = None,
            extension: str = "@cognigy/basic-nodes", comment: str = "") -> str:
        full = {**(self.defaults.get((type_, extension)) or {}), **(config or {})}
        node = self.api.call("POST", f"/flows/{self.flow_id}/chart/nodes", {
            "type": type_, "extension": extension, "label": label, "comment": comment,
            "config": full, "target": target, "mode": mode,
        })
        return node["_id"]

    def update(self, node_id: str, label: str, config: dict, comment: str = "") -> None:
        node = self.api.call("GET", f"/flows/{self.flow_id}/chart/nodes/{node_id}")
        self.api.call("PATCH", f"/flows/{self.flow_id}/chart/nodes/{node_id}",
                      {"label": label, "comment": comment, "config": {**node.get("config", {}), **config}})

    def chart(self) -> dict:
        return self.api.call("GET", f"/flows/{self.flow_id}/chart")

    def child(self, parent_id: str, type_: str) -> str:
        chart = self.chart()
        types = {n["_id"]: n["type"] for n in chart["nodes"]}
        relation = next(r for r in chart["relations"] if r["node"] == parent_id)
        return next(c for c in relation["children"] if types[c] == type_)

    def node_of_type(self, type_: str) -> str:
        return next(n["_id"] for n in self.chart()["nodes"] if n["type"] == type_)


# ---------------------------------------------------------------------------
# The build
# ---------------------------------------------------------------------------
def ensure_agent(api: Cognigy, project_id: str, route: Route) -> dict:
    """Creates the route's agent, or updates it in place so the flow's reference holds."""
    assert len(route.agent_instructions) <= 1000, f"{route.agent_name}: Cognigy caps an AI Agent's instructions at 1,000 characters"
    body = {
        "name": route.agent_name,
        "description": route.agent_description,
        "instructions": route.agent_instructions,
        # Neither call is remembered, so no contact profile reaches her.
        "contactProfilesOption": "none",
        "enableAutoLanguageDetection": False,
        # The call's own settings (speech()) set the voice; the agent names the same one.
        "enableVoiceConfigs": True,
        "voiceConfigs": {**voice_config(route), "ttsModel": "", "ttsDisableCache": False},
        "safetySettings": {
            "avoidHarmfulContent": True,
            "avoidUngroundedContent": True,
            "avoidCopyrightInfringements": True,
            "preventJailbreakAndManipulation": True,
        },
    }
    existing = next((a for a in api.items(f"/aiagents?projectId={project_id}&limit=100") if a["name"] == route.agent_name), None)
    if existing:
        api.call("PATCH", f"/aiagents/{existing['_id']}", body)
        return api.call("GET", f"/aiagents/{existing['_id']}")
    created = api.call("POST", "/aiagents", {**body, "projectId": project_id})
    return api.call("GET", f"/aiagents/{created['_id']}")


def fresh_flow(api: Cognigy, project_id: str, route: Route) -> dict:
    """The route's flow, deleted and made again so every run starts clean."""
    for flow in api.items(f"/flows?projectId={project_id}&limit=100"):
        if flow["name"] == route.flow_name:
            api.call("DELETE", f"/flows/{flow['_id']}")
    created = api.call("POST", "/flows", {"name": route.flow_name, "description": route.flow_description, "projectId": project_id})
    return api.call("GET", f"/flows/{created['_id']}")


def build_flow(api: Cognigy, flow_id: str, route: Route, agent: dict, mcp_url: str, mcp_secret: str | None) -> None:
    b = FlowBuilder(api, flow_id)
    start = b.node_of_type("start")

    # Once: the first turn of a call greets; every turn after goes to the agent.
    once = b.add("once", start, "append", "Greet once, then listen",
                 comment="The first execution is the call connecting. Every later one is the caller speaking.")
    first, afterwards = b.child(once, "onFirstExecution"), b.child(once, "afterwards")

    # Session settings for the whole call, speech included: on the trial the
    # endpoint can't hold speech settings (no Voice Gateway account of our
    # own), so without these the call can neither speak nor hear.
    session = b.add("setSessionConfig", first, "append", "Call settings", extension="@cognigy/voicegateway2", config={
        **speech(route),
        # Turn-taking. Deepgram ended a turn after a quarter second of quiet
        # (its default), so a caller pausing mid-thought had the rest of their
        # sentence arrive while she spoke, cutting off each line she had left.
        # A full second (Cognigy's most) lets people pause; three words to
        # talk over her, so "okay, yeah" or her own echo doesn't skip a line.
        "deepgramEndpointing": True,
        "deepgramEndpointingValue": 1000,
        "bargeInOnSpeech": True,
        "bargeInMinWordCount": 3,
        # People pause to think. After 20 quiet seconds, a gentle word, at
        # most twice; never a prompt to hurry.
        "userNoInputTimeoutEnable": True,
        "userNoInputMode": "speech",
        "userNoInputTimeout": 20000,
        "userNoInputRetries": 2,
        "userNoInputSpeech": route.still_here,
    }, comment="Deepgram speech, patient turn-taking, and a gentle line after 20 quiet seconds. Set in scripts/build_cognigy_voice.py.")
    # The flow runs the instant the call is answered, before the caller's audio
    # is flowing, so the greeting's first word ("Hi") was lost.
    pause = b.add("sleep", session, "append", "Let the line settle", config={"milliseconds": 800})
    b.add("say", pause, "append", "Greeting", config={"say": {"type": "text", "text": [route.greeting], "data": "", "linear": False, "loop": False, "_cognigy": {}}})

    # The agent's job for this call.
    job = b.add("aiAgentJob", afterwards, "append", route.agent_name, config={
        "aiAgent": agent["referenceId"],
        "name": route.job_name,
        "description": route.job_description,
        "instructions": route.job_instructions,
        "toolChoice": "auto",
        "memoryType": "inherit",  # the agent has no contact profile, so nothing is remembered
        "temperature": route.temperature,
        "maxTokens": 600,         # a few spoken sentences, or a short summary of a study answer
        "storeLocation": "stream",  # speak as it's written, a sentence at a time
        "outputImmediately": True,
        "errorHandling": "continue",
        "errorMessage": ERROR_LINE,
    }, comment="Edit the words in scripts/build_cognigy_voice.py and run it again.")

    # Cognigy adds a sample Tool under every new job; it becomes end_call.
    end_call = b.child(job, "aiAgentJobTool")
    b.update(end_call, "end_call", {
        "toolId": "end_call",
        "description": "End the call when the caller says goodbye or that they're finished. The call says goodbye for you.",
        "useParameters": False,
    })
    goodbye = b.add("say", end_call, "append", "Goodbye", config={"say": {"type": "text", "text": [route.goodbye], "data": "", "linear": False, "loop": False, "_cognigy": {}}})
    b.add("hangup", goodbye, "append", "Hang up", extension="@cognigy/voicegateway2",
          config={"hangupReason": "Caller finished", "hangupImmediately": False})

    # Adullam's MCP server: verses word for word, and a full study answer.
    mcp_config = {
        "name": "aquila",
        "mcpServerUrl": mcp_url,
        "timeout": 30,  # the most Cognigy allows; ask_aquila can take ten seconds or more
        "toolFilter": "whitelist",
        "whitelist": ["find_verses", "ask_aquila"],
        "cacheTools": True,
        "authType": "none",
    }
    if mcp_secret:
        # Checked when the stream opens (app/main.py::_guard_mcp).
        mcp_config["mcpHeaders"] = json.dumps({"Authorization": f"Bearer {mcp_secret}"})
    mcp = b.add("aiAgentJobMCPTool", job, "appendChild", "Adullam Scripture", config=mcp_config,
                comment="find_verses (about a second, no model) and ask_aquila (a full study answer) from Adullam.")
    b.add("aiAgentJobCallMCPTool", mcp, "append", "Call Adullam",
          config={"resolveImmediately": True},
          comment="Hands the tool's result straight back to Aquila.")


def ensure_endpoint(api: Cognigy, project_id: str, route: Route, flow: dict) -> dict:
    """The route's Voice Gateway endpoint, found by name or made, pointed at
    its flow. targetType isn't in the published schema, but the API takes it,
    and without it an endpoint made for an agent keeps answering with that agent."""
    target = {"targetType": "flow", "flowId": flow["referenceId"]}
    existing = next((e for e in api.items(f"/endpoints?projectId={project_id}&limit=100") if e["name"] == route.endpoint_name), None)
    if existing:
        api.call("PATCH", f"/endpoints/{existing['_id']}", target)
        return api.call("GET", f"/endpoints/{existing['_id']}")
    locale = api.items(f"/locales?projectId={project_id}&limit=1")[0]
    created = api.call("POST", "/endpoints", {
        "name": route.endpoint_name, "channel": "voiceGateway2", "projectId": project_id,
        "localeId": locale["referenceId"], **target,
    })
    return api.call("GET", f"/endpoints/{created['_id']}")


def build(api: Cognigy, project_id: str, route: Route, mcp_url: str, mcp_secret: str | None) -> None:
    agent = ensure_agent(api, project_id, route)
    print(f"AI Agent  {agent['name']}  {agent['_id']}")
    flow = fresh_flow(api, project_id, route)
    print(f"Flow      {flow['name']}  {flow['_id']}")
    build_flow(api, flow["_id"], route, agent, mcp_url, mcp_secret)
    print("          nodes built")
    endpoint = ensure_endpoint(api, project_id, route, flow)
    print(f"Endpoint  {endpoint['name']}  {endpoint['_id']}  config URL: https://endpoint-trial.cognigy.ai/{endpoint['URLToken']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--project", required=True, help="Cognigy project id")
    parser.add_argument("--route", choices=sorted(ROUTES), help="build only this call (both when left out)")
    parser.add_argument("--mcp-url", default=MCP_URL, help="Adullam's MCP SSE address")
    args = parser.parse_args()

    load_dotenv()
    url, key = os.environ.get("COGNIGY_API_URL"), os.environ.get("COGNIGY_API_KEY")
    if not (url and key):
        sys.exit("Set COGNIGY_API_URL and COGNIGY_API_KEY in .env first.")
    api = Cognigy(url, key)
    for name in [args.route] if args.route else ROUTES:
        print(f"-- {name}")
        build(api, args.project, ROUTES[name], args.mcp_url, os.environ.get("MCP_SECRET"))


if __name__ == "__main__":
    main()
