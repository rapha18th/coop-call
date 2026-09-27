"""The batch as a calendar, and any stretch of it in close-up."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from google.cloud import firestore

from . import config, flock, metrics, store, timeline


def _bounds(coop: dict) -> tuple[date, date]:
    today = store.local(store.now()).date()
    f = coop.get("flock")
    if f:
        placed = date.fromisoformat(f["placed"])
        return placed, max(today, placed + timedelta(days=f.get("sell_day") or 35))
    return today - timedelta(days=27), today


def _start(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=config.TZ)


def _since(coop_id: str, name: str, start: datetime, end: datetime) -> list[dict]:
    q = (store.coop_ref(coop_id).collection(name)
         .where(filter=firestore.FieldFilter("ts", ">=", start))
         .where(filter=firestore.FieldFilter("ts", "<", end)))
    return [{"id": d.id, **d.to_dict()} for d in q.stream()]


def _tone(day: dict, alarm_n: int) -> str:
    if not day.get("readings"):
        return "none"
    care = day.get("care") or 0
    tone = "good" if care >= 85 else "watch" if care >= 70 else "act"
    if day.get("dry_minutes", 0) >= 30:
        tone = "act"
    elif day.get("dry_minutes", 0) >= 10 and tone == "good":
        tone = "watch"
    if alarm_n and tone == "good":
        tone = "watch"
    return tone


def _plan(coop: dict) -> dict[str, list[str]]:
    f = coop.get("flock")
    if not f:
        return {}
    placed = date.fromisoformat(f["placed"])
    marks: dict[str, list[str]] = defaultdict(list)
    for day, text in flock.VACCINES:
        marks[(placed + timedelta(days=day)).isoformat()].append("vaccine:" + text.split(" in the")[0])
    for name, a, _ in flock.PHASES[1:]:
        marks[(placed + timedelta(days=a)).isoformat()].append("feed:" + name)
    for d in range(7, 50, 7):
        marks[(placed + timedelta(days=d)).isoformat()].append("weigh")
    marks[(placed + timedelta(days=f.get("sell_day") or 35)).isoformat()].append("sell")
    return marks


def month(coop: dict) -> dict:
    first, last = _bounds(coop)
    today = store.local(store.now()).date()
    start, end = _start(first), _start(last + timedelta(days=1))
    hours = timeline.hours_between(coop["id"], start, min(end, store.now()))
    by_day: dict[str, list[dict]] = defaultdict(list)
    for h in hours:
        by_day[h["hour"][:8]].append(h)
    alarms_by, calls_by, ledger_by = defaultdict(int), defaultdict(int), defaultdict(list)
    for a in _since(coop["id"], "alarms", start, end):
        alarms_by[store.local(a["ts"]).date().isoformat()] += 1
    for c in _since(coop["id"], "calls", start, end):
        calls_by[store.local(c["ts"]).date().isoformat()] += 1
    f = coop.get("flock")
    if f:
        for r in flock.ledger(coop["id"], f["batch"]):
            ledger_by[store.local(r["ts"]).date().isoformat()].append(r["kind"])
    plan = _plan(coop)
    placed = date.fromisoformat(f["placed"]) if f else None
    days = []
    d = first
    while d <= last:
        key = d.isoformat()
        summary = metrics._day(by_day.get(d.strftime("%Y%m%d"), []))
        days.append({
            "date": key, "age": (d - placed).days if placed else None,
            "future": d > today, "today": d == today,
            "tone": "future" if d > today else _tone(summary, alarms_by[key]),
            "care": summary.get("care"), "alarms": alarms_by[key], "calls": calls_by[key],
            "records": ledger_by[key], "plan": plan.get(key, []),
        })
        d += timedelta(days=1)
    return {"first": first.isoformat(), "last": last.isoformat(), "today": today.isoformat(), "days": days}


def _frames(hours: list[dict]) -> list[dict]:
    picks = []
    for h in hours:
        for n in h.get("notes", []):
            if n.get("frame"):
                picks.append({"ts": n["ts"], "frame": n["frame"], "text": n["text"]})
    last_by_day: dict[str, dict] = {}
    for h in hours:
        if h.get("frame"):
            last_by_day[h["hour"][:8]] = {"ts": h["last_ts"], "frame": h["frame"], "text": ""}
    picks += list(last_by_day.values())
    picks = sorted(picks, key=lambda p: p["ts"])[-4:]
    return [{"time": store.local(p["ts"]).strftime("%a %H:%M"), "url": store.frame_url(p["frame"]),
             "text": p["text"]} for p in picks]


def _story(summary: dict, per_day: list[dict], alarm_list: list[dict], n_days: int) -> str:
    if not summary.get("readings"):
        return "No camera readings in this stretch."
    bits = []
    calm = sum(1 for d in per_day if d.get("care") and d["care"] >= 85 and d.get("dry_minutes", 0) < 10)
    bits.append(f"{calm} of {n_days} days calm and comfortable." if n_days > 1 else
                ("A calm, comfortable day." if calm else "A day that needed attention."))
    if summary.get("dry_minutes", 0) >= 10:
        bits.append(f"The drinker was dry for about {summary['dry_minutes']} minutes in all.")
    if summary.get("cold", 0) >= 0.08:
        bits.append(f"The flock huddled {round(summary['cold'] * 100)}% of the time.")
    if summary.get("hot", 0) >= 0.05:
        bits.append(f"They panted {round(summary['hot'] * 100)}% of the time.")
    if alarm_list:
        bits.append(f"{len(alarm_list)} alarm{'s' if len(alarm_list) > 1 else ''} raised.")
    return " ".join(bits)


def span(coop: dict, first: date, last: date) -> dict:
    if last < first:
        first, last = last, first
    last = min(last, first + timedelta(days=41))
    start, end = _start(first), _start(last + timedelta(days=1))
    hours = timeline.hours_between(coop["id"], start, min(end, store.now()))
    summary = metrics._day(hours)
    by_day: dict[str, list[dict]] = defaultdict(list)
    for h in hours:
        by_day[h["hour"][:8]].append(h)
    n_days = (last - first).days + 1
    keys = [(first + timedelta(days=i)).strftime("%Y%m%d") for i in range(n_days)]
    per_day = [{"day": k, **metrics._day(by_day.get(k, []))} for k in keys]
    grid = []
    for k in keys[-14:]:
        lookup = {h["hour"][8:10]: h for h in by_day.get(k, [])}
        grid.append({"day": k, "hours": [metrics.cell(lookup.get(f"{i:02d}")) for i in range(24)]})
    alarm_list = _since(coop["id"], "alarms", start, end)
    calls = _since(coop["id"], "calls", start, end)
    out = {
        "first": first.isoformat(), "last": last.isoformat(), "days": n_days,
        "summary": summary, "per_day": per_day, "grid": grid,
        "story": _story(summary, per_day, alarm_list, n_days),
        "alarms": [{"time": store.local(a["ts"]).strftime("%a %H:%M"), "message": a["message"],
                    "status": a["status"]} for a in sorted(alarm_list, key=lambda a: a["ts"])],
        "calls": [{"time": store.local(c["ts"]).strftime("%a %H:%M"), "name": c.get("name") or "Caller",
                   "duration_s": c.get("duration_s"), "said": next((l["text"] for l in c.get("transcript", [])
                                                                    if l.get("who") == "coop"), "")}
                  for c in sorted(calls, key=lambda c: c["ts"])],
        "frames": _frames(hours),
        "flock": None, "records": [],
    }
    f = coop.get("flock")
    if f:
        st = flock.state(coop)
        placed = date.fromisoformat(f["placed"])
        a0, a1 = (first - placed).days, (last - placed).days
        factor = st["growth"]["factor"] if st else 0.75
        alive = st["birds"]["alive"] if st else f["birds_placed"]
        feed_kg = sum(flock.target(d)["feed_g"] or 0 for d in range(max(1, a0), max(1, a1) + 1)) * alive / 1000
        out["flock"] = {
            "age_from": a0, "age_to": a1,
            "weight_from": round(flock.target(max(0, a0))["weight_g"] * factor / 1000, 2),
            "weight_to": round(flock.target(max(0, a1))["weight_g"] * factor / 1000, 2),
            "feed_kg": round(feed_kg), "feed_bags": round(feed_kg / flock.BAG_KG, 1),
            "feed_usd": round(feed_kg * f["prices"]["feed_per_kg"]),
            "plan": [{"date": k, "what": v} for k, v in sorted(_plan(coop).items()) if first.isoformat() <= k <= last.isoformat()],
        }
        out["records"] = [{"time": store.local(r["ts"]).strftime("%a %d %b"), "kind": r["kind"],
                           "quantity": r.get("quantity"), "unit": r.get("unit"), "amount_usd": r.get("amount_usd"),
                           "note": r.get("note")} for r in flock.ledger(coop["id"], f["batch"])
                          if first <= store.local(r["ts"]).date() <= last]
    return out
