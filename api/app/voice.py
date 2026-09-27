"""The coop's voice: an AssemblyAI Voice Agent session, configured per call."""

from __future__ import annotations

import httpx

from . import alarms, config, store

AGENTS_API = "https://agents.assemblyai.com/v1"
VOICE = "anna"

KEYTERMS = [
    "brooder", "drinker", "drinkers", "feeder", "broilers", "layers", "Newcastle",
    "coccidiosis", "gumboro", "vaccine", "litter", "chick", "chicks", "coop", "Ziso",
]

TIME_ARGS = {
    "type": "string",
    "description": "Local date and time in ISO format, e.g. 2026-09-26T02:00. Work it out from the current local time.",
}

TOOLS = [
    {
        "type": "function",
        "name": "coop_now",
        "description": "What the coop looks like right now: birds, flock spread, feeder, drinker, sound, the coop phone's battery. Use for any question about the present.",
        "parameters": {"type": "object", "properties": {}},
        "execution_mode": "hold",
        "timeout_seconds": 20,
    },
    {
        "type": "function",
        "name": "coop_period",
        "description": "Hour by hour account of a period, e.g. overnight, this morning, between two and four. Use for any question about the past.",
        "parameters": {
            "type": "object",
            "properties": {"start": TIME_ARGS, "end": TIME_ARGS},
            "required": ["start", "end"],
        },
        "execution_mode": "hold",
        "timeout_seconds": 20,
    },
    {
        "type": "function",
        "name": "coop_vs_normal",
        "description": "Compare this hour with the same hour on earlier days. Use when asked if anything is unusual or different.",
        "parameters": {"type": "object", "properties": {}},
        "execution_mode": "hold",
        "timeout_seconds": 20,
    },
    {
        "type": "function",
        "name": "show_picture",
        "description": "Put the camera frame nearest a time on the owner's screen as evidence. Use whenever you describe something the owner may want to see, or when asked to show.",
        "parameters": {
            "type": "object",
            "properties": {"time": {**TIME_ARGS, "description": TIME_ARGS["description"] + " Use now for the latest."}},
            "required": ["time"],
        },
        "execution_mode": "interactive",
        "timeout_seconds": 20,
    },
    {
        "type": "function",
        "name": "coop_alarms",
        "description": "Open alarms: what is wrong, since when.",
        "parameters": {"type": "object", "properties": {}},
        "execution_mode": "hold",
        "timeout_seconds": 20,
    },
    {
        "type": "function",
        "name": "resolve_alarm",
        "description": "Mark an alarm handled once the owner says they have dealt with it.",
        "parameters": {
            "type": "object",
            "properties": {"alarm_id": {"type": "string"}},
            "required": ["alarm_id"],
        },
        "execution_mode": "interactive",
        "timeout_seconds": 20,
    },
]


def system_prompt(coop: dict, alarm: dict | None) -> str:
    now = store.local(store.now())
    lines = [
        f"You are {coop['name']}, a poultry house, speaking on a phone call with its owner, "
        f"{coop.get('owner_name') or 'the owner'}. You speak for the house in the first person plural "
        "for the birds: we, our drinker, our feeder. You see through a phone camera and hear through its "
        "microphone, and you remember everything as a timeline.",
        f"The local time is {now.strftime('%A %d %B %Y, %H:%M')} (Central Africa Time).",
        f"The flock should be about {coop.get('birds_expected', 'an unknown number of')} birds.",
        "Always answer from your tools, never from imagination. Any question about the past, even one word "
        "like yesterday or last night, needs coop_period for that window; coop_alarms only lists alarms still "
        "open. Give times and numbers. When you describe "
        "something visible, also call show_picture so the owner sees the evidence. If a tool says demo data, "
        "you may still answer.",
        "Keep every reply to one to three short spoken sentences. No lists, no formatting, no exclamation "
        "marks. Plain English that a farmer in Zimbabwe or South Africa uses.",
        "You watch and report. You are not a vet. For illness, deaths or a bird lying still, say what you "
        "see and suggest calling a vet or extension officer. Suggest practical fixes: refill the drinker, "
        "check the brooder heat, open a vent.",
    ]
    if alarm:
        lines.append(f"You called the owner because of an alarm (id {alarm['id']}): {alarm['message']} "
                     "Open with that, show the picture, then answer questions. When the owner says it is "
                     "handled, call resolve_alarm.")
    return "\n\n".join(lines)


def greeting(coop: dict, alarm: dict | None) -> str:
    if alarm:
        return f"Hello, it's {coop['name']}. {alarm['message']} Shall I show you?"
    return f"Hello, it's {coop['name']}. Ask me anything about the birds."


def session(coop: dict, alarm_id: str | None) -> dict:
    alarm = alarms.get_alarm(coop["id"], alarm_id) if alarm_id else None
    if alarm and alarm["status"] == "ringing":
        alarms.set_status(coop["id"], alarm["id"], "answered")
    return {
        "system_prompt": system_prompt(coop, alarm),
        "greeting": greeting(coop, alarm),
        "tools": TOOLS,
        "input": {"keyterms": KEYTERMS, "language_codes": ["en"]},
        "output": {"voice": VOICE},
    }


def mint_token() -> str:
    r = httpx.get(
        f"{AGENTS_API}/token",
        params={"product": "voice_agent", "expires_in_seconds": 60,
                "max_session_duration_seconds": config.CALL_MAX_SECONDS},
        headers={"Authorization": f"Bearer {config.ASSEMBLYAI_API_KEY}"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["token"]
