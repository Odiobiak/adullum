"""Builds Aquila's voice call for Refuge in a Cognigy.AI project, from code.

Refuge's "Talk out loud" (web/refuge.js::talkRoom) opens Cognigy's WebRTC
widget, and the call is answered by what this script builds:

    AI Agent "Aquila"        who she is (persona, safety settings, no memory)
    Flow "Aquila Refuge Voice"
      Start
      Once
        On first time   Set Session Config (barge-in, gentle no-input)
                        Say the greeting
        Afterwards      AI Agent job "Refuge voice companion"
                          Default            her spoken reply
                          MCP Tool "aquila"  find_verses and ask_aquila on
                            Call MCP Tool    Adullam's /mcp/sse (app/mcp_server.py)
                          Tool "end_call"    Say goodbye, Hang Up
      End
    Endpoint                 pointed at the flow

Running it again rebuilds the flow from scratch and updates the agent in
place, so this file is the source of truth: change the words here, not in
the Cognigy editor (a rerun wipes editor changes). Speech is set for the
call by the Call settings node (SPEECH), since the trial endpoint can't hold
speech settings. Turning off debug messages once testing is done stays manual
(docs/cognigy-voice.md).

Reads from .env: COGNIGY_API_URL, COGNIGY_API_KEY, and MCP_SECRET (optional;
when set, the MCP tool sends it as a Bearer header).

    python scripts/build_cognigy_voice.py --project <projectId> --endpoint <endpointId>
"""

import argparse
import json
import os
import sys

import httpx
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# What Aquila says and how she behaves. House style applies: no em dashes.
# ---------------------------------------------------------------------------
AGENT_NAME = "Aquila"
FLOW_NAME = "Aquila Refuge Voice"
MCP_URL = "https://adullum.onrender.com/mcp/sse"

AGENT_DESCRIPTION = (
    "A warm and steadfast companion who loves God. She listens first, and shares "
    "Scripture only when it's wanted, quoting it word for word."
)

# The AI Agent's own instructions are capped at 1,000 characters by Cognigy,
# so they hold who she is; how to behave on this call lives on the job below.
AGENT_INSTRUCTIONS = (
    "You are Aquila, a warm and steadfast companion who loves God. You're speaking with "
    "someone in Refuge, a quiet, private room in the Adullam app. People come in every "
    "kind of season: carrying something heavy, hoping, planning with God, giving thanks, "
    "or just needing to be heard. Listen first. Speak like a friend sitting beside them: "
    "plain, gentle and brief, then let them talk. Never tell them how to feel, never "
    "lecture, and never press a meaning on them. Never claim God told you something, and "
    "never promise an outcome. You are not a pastor or a counsellor and never pretend to "
    "be. Never use an em dash."
)

JOB_NAME = "Refuge voice companion"
JOB_DESCRIPTION = (
    "Listen to the caller in Refuge and reply in a few spoken sentences. When they want "
    "Scripture, look it up with find_verses and quote only what it returns."
)

JOB_INSTRUCTIONS = """This is a voice call. Everything you say is spoken aloud.
- Reply in two to four short sentences, then stop and let them talk. Ask at most one gentle question.
- No lists, headings, symbols or emojis. Say a reference the way a person would: "John chapter fourteen, verse twenty-seven".
- Show you heard them in your own words. Don't rush to fix or explain. When they're hopeful or grateful, be glad with them.

Scripture
- Offer Scripture only when they ask for it, or say yes when you gently offer.
- Then call find_verses with a short topic ("peace when anxious") or the reference they named. Quote only verses it returns, word for word, and say each reference. Choose one or two, not all.
- If it returns nothing, say you couldn't find the verse just now. Never quote or paraphrase Scripture from memory.
- For a real Bible study question (what a passage means, who wrote it, its background), call ask_aquila and share the heart of its answer in a few sentences, keeping its references. Tell them it may take a moment.
- What the text says, say plainly. What it might mean for them, offer as a question, never as a conclusion. Where Christians disagree, give the range of views, not one tradition's.

Care
- If they might be in danger, or thinking of harming themselves or someone else, set everything else aside. Tell them gently that they deserve a real person with them right now: in an emergency, call the local emergency number; in the US, call or text 988; in the UK or Ireland, call Samaritans on 116 123; and "Talk to a person" in Refuge lists more. Stay with them warmly and never end the call yourself.

Privacy
- Don't ask for names, places or contact details. Nothing from this call is remembered.

Ending
- When they say goodbye or that they're finished, call end_call. Don't say goodbye yourself first; the call does that."""

GREETING = "Hi, I'm Aquila. I'm here to listen. What's on your heart today?"
STILL_HERE = "I'm still here, whenever you're ready."
# Speech for the call, through the shared trial Voice Gateway's own Deepgram
# credential. The gateway finds a credential by vendor and label together, so
# both are named: without the label, or with Flux (it has no Flux credential),
# the gateway hung up the moment the call tried to speak or listen.
SPEECH = {
    "sttVendor": "deepgram",
    "sttLabel": "deepgram",
    "sttLanguage": "en-US",
    "ttsVendor": "deepgram",
    "ttsLabel": "deepgram",
    "ttsLanguage": "en-US",
    "ttsVoice": "aura-2-ophelia-en",  # calm and clear; the gateway's default is aura-2-andromeda-en
}

GOODBYE = "Thank you for sharing this time with me. Go gently. Refuge is here whenever you need it."
ERROR_LINE = "I'm sorry, I lost my words for a moment. Could you say that again?"


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
def ensure_agent(api: Cognigy, project_id: str) -> dict:
    """Creates Aquila, or updates her in place so the flow's reference holds."""
    assert len(AGENT_INSTRUCTIONS) <= 1000, "Cognigy caps an AI Agent's instructions at 1,000 characters"
    body = {
        "name": AGENT_NAME,
        "description": AGENT_DESCRIPTION,
        "instructions": AGENT_INSTRUCTIONS,
        # Refuge promises a talk is never remembered, so no contact profile reaches her.
        "contactProfilesOption": "none",
        "enableAutoLanguageDetection": False,
        # The voice is set for the call by the flow's Call settings (SPEECH).
        "enableVoiceConfigs": False,
        "safetySettings": {
            "avoidHarmfulContent": True,
            "avoidUngroundedContent": True,
            "avoidCopyrightInfringements": True,
            "preventJailbreakAndManipulation": True,
        },
    }
    existing = next((a for a in api.items(f"/aiagents?projectId={project_id}&limit=100") if a["name"] == AGENT_NAME), None)
    if existing:
        api.call("PATCH", f"/aiagents/{existing['_id']}", body)
        return api.call("GET", f"/aiagents/{existing['_id']}")
    created = api.call("POST", "/aiagents", {**body, "projectId": project_id})
    return api.call("GET", f"/aiagents/{created['_id']}")


def fresh_flow(api: Cognigy, project_id: str) -> dict:
    """The voice flow, deleted and made again so every run starts clean."""
    for flow in api.items(f"/flows?projectId={project_id}&limit=100"):
        if flow["name"] == FLOW_NAME:
            api.call("DELETE", f"/flows/{flow['_id']}")
    created = api.call("POST", "/flows", {
        "name": FLOW_NAME,
        "description": "Aquila's voice call in Refuge. Built by scripts/build_cognigy_voice.py; edit there, not here.",
        "projectId": project_id,
    })
    return api.call("GET", f"/flows/{created['_id']}")


def build_flow(api: Cognigy, flow_id: str, agent: dict, mcp_url: str, mcp_secret: str | None) -> None:
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
        **SPEECH,
        # The caller can talk over her; two words, so a "mm" doesn't cut her off.
        "bargeInOnSpeech": True,
        "bargeInMinWordCount": 2,
        # People in Refuge pause to think. After 20 quiet seconds, a gentle
        # word, at most twice; never a prompt to hurry.
        "userNoInputTimeoutEnable": True,
        "userNoInputMode": "speech",
        "userNoInputTimeout": 20000,
        "userNoInputRetries": 2,
        "userNoInputSpeech": STILL_HERE,
    }, comment="Deepgram speech, barge-in on, and a gentle line after 20 quiet seconds. Set in scripts/build_cognigy_voice.py.")
    b.add("say", session, "append", "Greeting", config={"say": {"type": "text", "text": [GREETING], "data": "", "linear": False, "loop": False, "_cognigy": {}}})

    # The agent's job for this call.
    job = b.add("aiAgentJob", afterwards, "append", "Aquila", config={
        "aiAgent": agent["referenceId"],
        "name": JOB_NAME,
        "description": JOB_DESCRIPTION,
        "instructions": JOB_INSTRUCTIONS,
        "toolChoice": "auto",
        "memoryType": "inherit",  # the agent has no contact profile, so nothing is remembered
        "temperature": 0.5,       # warm, but steady
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
    goodbye = b.add("say", end_call, "append", "Goodbye", config={"say": {"type": "text", "text": [GOODBYE], "data": "", "linear": False, "loop": False, "_cognigy": {}}})
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


def point_endpoint(api: Cognigy, endpoint_id: str, flow: dict) -> dict:
    """Points the voice endpoint at the flow instead of an agent. targetType
    isn't in the published schema, but the API takes it, and without it an
    endpoint made for an agent keeps answering with that agent."""
    api.call("PATCH", f"/endpoints/{endpoint_id}", {"targetType": "flow", "flowId": flow["referenceId"]})
    return api.call("GET", f"/endpoints/{endpoint_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--project", required=True, help="Cognigy project id")
    parser.add_argument("--endpoint", help="voice endpoint id to point at the flow")
    parser.add_argument("--mcp-url", default=MCP_URL, help="Adullam's MCP SSE address")
    args = parser.parse_args()

    load_dotenv()
    url, key = os.environ.get("COGNIGY_API_URL"), os.environ.get("COGNIGY_API_KEY")
    if not (url and key):
        sys.exit("Set COGNIGY_API_URL and COGNIGY_API_KEY in .env first.")
    api = Cognigy(url, key)

    agent = ensure_agent(api, args.project)
    print(f"AI Agent  {agent['name']}  {agent['_id']}")
    flow = fresh_flow(api, args.project)
    print(f"Flow      {flow['name']}  {flow['_id']}")
    build_flow(api, flow["_id"], agent, args.mcp_url, os.environ.get("MCP_SECRET"))
    print("          nodes built")
    if args.endpoint:
        endpoint = point_endpoint(api, args.endpoint, flow)
        print(f"Endpoint  {endpoint['name']}  flow={endpoint.get('flowId')}  target={endpoint.get('targetType')}")


if __name__ == "__main__":
    main()
