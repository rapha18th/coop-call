"""Today in one sentence, and the few things to do about it."""

from __future__ import annotations

from . import alarms, device, flock, metrics, store, timeline

ALARM_VERBS = {
    "drinker_empty": ("Refill the drinker", "It has been empty"),
    "feeder_empty": ("Fill the feeder", "It has been empty"),
    "huddled": ("Check the brooder heat", "The birds are huddling"),
    "heat": ("Cool the house", "The birds are panting"),
    "unusual": ("Look at the coop", "Something unusual"),
    "node_silent": ("Check the coop phone", "It stopped reporting"),
}


def _care_today(coop: dict) -> dict:
    now = store.now()
    start = store.local(now).replace(hour=0, minute=0, second=0, microsecond=0)
    return metrics._day(timeline.hours_between(coop["id"], start, now))


def actions(coop: dict, st: dict | None, dev: dict, open_alarms: list[dict]) -> list[dict]:
    out: list[dict] = []
    for a in open_alarms:
        verb, why = ALARM_VERBS.get(a["kind"], ("Look at the coop", "Alarm"))
        first = ({"label": "Details", "do": "open", "sheet": "phone"} if a["kind"] == "node_silent"
                 else {"label": "See it", "do": "call", "alarm": a["id"]})
        out.append({"id": f"alarm-{a['id']}", "tone": "act", "title": verb,
                    "detail": f"{a['message']} Raised {timeline.clock(a['ts'])}.",
                    "buttons": [first, {"label": "Fixed", "do": "resolve", "alarm": a["id"]}]})
    if dev["level"] == "down" and not any(a["kind"] == "node_silent" for a in open_alarms) and dev.get("frames"):
        out.append({"id": "device", "tone": "watch", "title": "Check the coop phone", "detail": dev["summary"],
                    "buttons": [{"label": "Details", "do": "open", "sheet": "phone"}]})
    if not st:
        return out
    for t in st["tasks"]:
        if t["when"] == "daily":
            continue
        late = "overdue" in t["when"] or t["when"] == "now"
        if t["kind"] == "vaccine":
            name = t["text"].split(": ", 1)[1].split(" in the")[0]
            out.append({"id": f"vax-{name}", "tone": "act" if late else "watch", "title": f"Give the {name[0].lower() + name[1:] if name.split()[0] in ('Day',) else name}",
                        "detail": f"{t['when'].capitalize()} · in the drinking water. Check the product with your supplier.",
                        "buttons": [{"label": "Done", "do": "log", "kind": "vaccinated", "note": name}]})
        elif t["kind"] == "feed" and "lasts" in t["text"]:
            f = st["feed"]
            out.append({"id": "buy-feed", "tone": "act", "title": "Buy feed",
                        "detail": f"About {f['on_hand_kg']} kg left, enough for {f['days_left']} days. "
                                  f"The birds eat {round(f['today_kg'])} kg a day and rising.",
                        "buttons": [{"label": "Log a purchase", "do": "form", "kind": "feed_bought"}]})
        elif t["kind"] == "feed":
            nxt = st["next_phase"] or "finisher"
            out.append({"id": "switch", "tone": "watch", "title": f"Switch to {nxt.lower()}",
                        "detail": t["text"].split(". ", 1)[0] + ".",
                        "buttons": [{"label": "Done", "do": "log", "kind": "note", "note": f"Switched to {nxt.lower()}"}]})
        elif t["kind"] == "weigh":
            out.append({"id": "weigh", "tone": "watch", "title": "Weigh ten birds",
                        "detail": "Every projection rests on it.",
                        "buttons": [{"label": "Log a weight", "do": "form", "kind": "weighed"}]})
    weighs = st["growth"]["weighs"]
    if not weighs or st["age_days"] - weighs[-1]["day"] >= 8:
        if not any(a["id"] == "weigh" for a in out) and st["age_days"] >= 7:
            last = f"Last weigh-in on day {weighs[-1]['day']}." if weighs else "No weigh-in yet."
            out.append({"id": "weigh", "tone": "watch", "title": "Weigh ten birds",
                        "detail": f"{last} Projections assume {round(st['growth']['factor'] * 100)}% of the breed target.",
                        "buttons": [{"label": "Log a weight", "do": "form", "kind": "weighed"}]})
    best = st["money"]["best_day"]
    if best and 0 <= best - st["age_days"] <= 4:
        out.append({"id": "sell", "tone": "watch", "title": "Line up the buyer",
                    "detail": f"The best day to sell is day {best}, in {best - st['age_days']} days.",
                    "buttons": [{"label": "The numbers", "do": "open", "sheet": "money"}]})
    order = {"act": 0, "watch": 1}
    return sorted(out, key=lambda a: order[a["tone"]])


def headline(coop: dict, st: dict | None, care: dict, dev: dict, acts: list[dict]) -> dict:
    parts: list[str] = []
    level = "good"
    if care.get("readings"):
        worries = []
        if (care.get("dry_minutes") or 0) >= 10:
            worries.append(f"the drinker ran dry for {care['dry_minutes']} minutes")
        if (care.get("cold") or 0) >= 0.2:
            worries.append("the birds huddled from cold")
        if (care.get("hot") or 0) >= 0.2:
            worries.append("the birds panted from heat")
        if worries:
            parts.append("Today " + " and ".join(worries) + ".")
            level = "watch"
        else:
            parts.append("Calm, fed and watered today.")
    elif dev["level"] == "down":
        parts.append("The coop phone is not reporting, so today is unseen.")
        level = "watch"
    if st:
        gap = 1 - st["growth"]["estimate_kg"] / st["growth"]["target_kg"]
        if gap > 0.1:
            parts.append(f"About {round(gap * 100)}% under the breed weight.")
        f = st["feed"]
        if f["days_left"] is not None and f["days_left"] <= 5:
            parts.append(f"Feed runs out in {f['days_left']} days.")
    if any(a["tone"] == "act" for a in acts):
        level = "act"
    return {"level": level, "text": " ".join(parts) or "No readings yet."}


def build(coop: dict) -> dict:
    st = flock.state(coop)
    dev = device.health(coop)
    raw_alarms = alarms.open_alarms(coop["id"])
    acts = actions(coop, st, dev, raw_alarms)
    care = _care_today(coop)
    return {"headline": headline(coop, st, care, dev, acts), "actions": acts, "care": care}
