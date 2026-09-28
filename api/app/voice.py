"""The coop's voice: an AssemblyAI Voice Agent session, configured per call."""

from __future__ import annotations

import httpx

from . import alarms, config, store

AGENTS_API = "https://agents.assemblyai.com/v1"
VOICE = "anna"

KEYTERMS = [
    "brooder", "drinker", "drinkers", "feeder", "broilers", "layers", "Newcastle",
    "coccidiosis", "gumboro", "vaccine", "litter", "chick", "chicks", "coop", "Ziso",
    "starter", "grower", "finisher", "bags", "kilos", "Cobb", "Irvine's", "margin",
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
        "name": "coop_week",
        "description": "This week's flock metrics and advice: care score, water and feed availability, minutes the drinker was dry, cold and heat, calm nights, bird count, flock age. Use for how are we doing, what should I change, any advice.",
        "parameters": {"type": "object", "properties": {}},
        "execution_mode": "hold",
        "timeout_seconds": 25,
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


BUSINESS_TOOLS = [
    {
        "type": "function",
        "name": "flock_status",
        "description": "The flock as a business: age, phase, birds alive and lost, estimated weight against the breed target, feed today in kg and bags, feed on hand and days it lasts, feed by week in bags and dollars, money spent so far. Use for any question about growth, feed, costs or how the batch is going.",
        "parameters": {"type": "object", "properties": {}},
        "execution_mode": "hold",
        "timeout_seconds": 25,
    },
    {
        "type": "function",
        "name": "sell_plan",
        "description": "Projected margin for selling on different days, the best day, and what one more day is worth (weight gained minus feed eaten). Use for when should I sell, is it worth waiting, what will I make.",
        "parameters": {"type": "object", "properties": {
            "day": {"type": "integer", "description": "A specific age in days the owner asks about, optional."}}},
        "execution_mode": "hold",
        "timeout_seconds": 25,
    },
    {
        "type": "function",
        "name": "today_tasks",
        "description": "The routine for today at this age: vaccines due, feed phase changes, weighing, brooding temperature, lighting.",
        "parameters": {"type": "object", "properties": {}},
        "execution_mode": "hold",
        "timeout_seconds": 20,
    },
    {
        "type": "function",
        "name": "device_status",
        "description": "Health of the coop phone that watches the birds: online, battery, charging, network, whether the camera view is clear.",
        "parameters": {"type": "object", "properties": {}},
        "execution_mode": "hold",
        "timeout_seconds": 20,
    },
    {
        "type": "function",
        "name": "log_record",
        "description": "Save a farm record the owner tells you about. Read it back and get a yes before saving. Kinds: feed_bought (quantity in kg, a 50 kg bag is 50), deaths (number of birds), sold (number of birds, amount_usd received), weighed (average kg per bird), expense (amount_usd, note what for), vaccinated (note which vaccine), note.",
        "parameters": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["feed_bought", "deaths", "sold", "weighed", "expense", "vaccinated", "note"]},
            "quantity": {"type": "number"},
            "unit": {"type": "string"},
            "amount_usd": {"type": "number"},
            "note": {"type": "string"}},
            "required": ["kind"]},
        "execution_mode": "interactive",
        "timeout_seconds": 20,
    },
]
TOOLS = TOOLS + BUSINESS_TOOLS


def system_prompt(coop: dict, alarm: dict | None, briefing: str = "", device_text: str = "") -> str:
    now = store.local(store.now())
    lines = [
        f"You are {coop['name']}, a broiler house, on a call with its owner, "
        f"{coop.get('owner_name') or 'the owner'}. Speak for the house and the birds in the first person "
        "plural: we, our drinker. You see through a phone camera, you remember everything as a timeline, "
        "and you keep the farm's books.",
        f"The local time is {now.strftime('%A %d %B %Y, %H:%M')} (Central Africa Time).",
        "Briefing, true as of this call: " + briefing,
        device_text,
        "How you work. Answer from tools, never from imagination. Questions about the past need coop_period "
        "for that window. Questions about growth, feed, cost or money need flock_status. Questions about "
        "when to sell need sell_plan. Questions about what to do need today_tasks. When you describe "
        "something visible, call show_picture so the owner sees the evidence.",
        "Think like a good farm manager. Tie what you see to money: a dry drinker costs growth, cold nights "
        "cost feed. Feed is most of the cost, and weeks five and six eat more than half of it, so warn early "
        "when feed on hand runs short and when each extra day stops paying for itself. Records are optional: work "
        "from what the camera sees and the breed model, and never ask the owner to enter data. When you name a sell "
        "day, give the reason in one clause, for example that the birds are behind target so each day still adds "
        "more weight than it costs in feed.",
        "When the owner tells you something that happened (bought feed, birds died, sold birds, weighed "
        "birds, vaccinated), offer to record it. Read the record back in one sentence and save it with "
        "log_record only after a yes.",
        "Keep every reply to one to three short spoken sentences. Round numbers. Say dollars, not USD. No "
        "lists, no formatting, no exclamation marks. Plain English for a farmer in Zimbabwe or South Africa.",
        "You are not a vet. For illness, deaths or a bird lying still, say what you see and suggest the vet "
        "or an extension officer. Prices and targets are estimates; say so when the owner makes a big "
        "decision on them.",
    ]
    if alarm:
        lines.append(f"You called the owner because of an alarm (id {alarm['id']}): {alarm['message']} "
                     "Open with that, show the picture, say what it costs if left, then answer questions. "
                     "When the owner says it is handled, call resolve_alarm.")
    return "\n\n".join(l for l in lines if l)


def greeting(coop: dict, alarm: dict | None) -> str:
    if alarm:
        return f"Hello, it's {coop['name']}. {alarm['message']} Shall I show you?"
    return f"Hello, it's {coop['name']}. Ask me about the birds, the feed, or the money."


def session(coop: dict, alarm_id: str | None, by: str | None = None, briefing: str = "",
            device_text: str = "") -> dict:
    alarm = alarms.get_alarm(coop["id"], alarm_id) if alarm_id else None
    if alarm and alarm["status"] == "ringing":
        alarms.set_status(coop["id"], alarm["id"], "answered", by)
    return {
        "system_prompt": system_prompt(coop, alarm, briefing, device_text),
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
