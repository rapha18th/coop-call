"""Flock metrics a keeper can act on, computed from the hourly rollups."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import median

from google.cloud import firestore

from . import store, timeline

NIGHT = set(range(19, 24)) | set(range(0, 6))
CARE_WEIGHTS = {"water": 0.35, "comfort": 0.30, "feed": 0.20, "calm_nights": 0.15}


def _share(h: dict, key: str) -> float:
    return h.get(key, 0) / h["nv"] if h.get("nv") else 0.0


def _hot(h: dict) -> int:
    return max(h.get("panting", 0), h.get("hot_spread", 0))


def cell(h: dict | None) -> dict:
    """One hour of the week grid: the thermal state, plus flags for water, feed and notes."""
    if not h or not h.get("nv"):
        return {"state": "none"}
    cold, hot = _share(h, "huddled"), _hot(h) / h["nv"]
    state = "cold" if cold >= 0.3 else "hot" if hot >= 0.3 else "fine"
    return {
        "state": state,
        "water": _share(h, "drinker_low") >= 0.3,
        "feed": _share(h, "feeder_low") >= 0.3,
        "note": bool(h.get("notes")),
        "birds": round(h["birds_sum"] / h["nv"]),
    }


def _day(hours: list[dict]) -> dict:
    nv = sum(h.get("nv", 0) for h in hours)
    if not nv:
        return {"readings": 0, "coverage_h": 0}
    night = [h for h in hours if int(h["hour"][8:10]) in NIGHT]
    night_nv = sum(h.get("nv", 0) for h in night)
    water_ok = 1 - sum(h.get("drinker_low", 0) for h in hours) / nv
    feed_ok = 1 - sum(h.get("feeder_low", 0) for h in hours) / nv
    cold = sum(h.get("huddled", 0) for h in hours) / nv
    hot = sum(_hot(h) for h in hours) / nv
    comfort = max(0.0, 1 - cold - hot)
    calm = 1 - (sum(h.get("agitated", 0) for h in night) / night_nv) if night_nv else 1.0
    parts = {"water": water_ok, "comfort": comfort, "feed": feed_ok, "calm_nights": calm}
    return {
        "readings": nv,
        "coverage_h": sum(1 for h in hours if h.get("nv")),
        "water_ok": round(water_ok, 3),
        "dry_minutes": round(sum(_share(h, "drinker_empty") * 60 for h in hours)),
        "feed_ok": round(feed_ok, 3),
        "empty_feeder_minutes": round(sum(_share(h, "feeder_empty") * 60 for h in hours)),
        "cold": round(cold, 3),
        "hot": round(hot, 3),
        "comfort": round(comfort, 3),
        "calm_nights": round(calm, 3),
        "birds_mean": round(sum(h.get("birds_sum", 0) for h in hours) / nv, 1),
        "birds_max": max((h.get("birds_max", 0) for h in hours), default=0),
        "care": round(100 * sum(CARE_WEIGHTS[k] * v for k, v in parts.items())),
        "simulated": any(h.get("simulated") for h in hours),
    }


def _repeat_hours(days: list[list[dict]], test, min_days: int = 2) -> list[int]:
    """Clock hours where a condition held on at least min_days of the given days."""
    hits: Counter = Counter()
    for hours in days:
        for h in hours:
            if h.get("nv") and test(h):
                hits[int(h["hour"][8:10])] += 1
    return sorted(hr for hr, n in hits.items() if n >= min_days)


def _span(hours: list[int]) -> str:
    return f"{hours[0]:02d}:00" if len(hours) == 1 else f"{hours[0]:02d}:00 to {hours[-1] + 1:02d}:00"


def insights(coop: dict, days: list[list[dict]], today: dict) -> list[dict]:
    out: list[dict] = []
    recent = days[-3:]
    if today.get("readings"):
        if today.get("dry_minutes", 0) >= 10:
            worst = max(days[-1], key=lambda h: _share(h, "drinker_empty"))
            out.append({"kind": "water", "level": "act",
                        "text": f"The drinker was dry for about {today['dry_minutes']} minutes today, "
                                f"worst around {worst['hour'][8:10]}:00. Refill before that hour or add a drinker."})
        cold = _repeat_hours(recent, lambda h: _share(h, "huddled") >= 0.3)
        if cold:
            out.append({"kind": "cold", "level": "act",
                        "text": f"The flock huddled around {_span(cold)} on more than one night. "
                                "The brooder may be too weak then; check the heat before that hour."})
        hot = _repeat_hours(recent, lambda h: _hot(h) / h["nv"] >= 0.3)
        if hot:
            out.append({"kind": "hot", "level": "act",
                        "text": f"Birds panted around {_span(hot)} on more than one day. "
                                "Open vents or add shade before that hour."})
        feed = _repeat_hours(recent, lambda h: _share(h, "feeder_low") >= 0.3)
        if feed:
            out.append({"kind": "feed", "level": "watch",
                        "text": f"The feeder runs low around {_span(feed)}. Fill it later in the evening "
                                "or add a second feeder."})
        expected = coop.get("birds_expected") or 0
        if expected and today.get("birds_max", 0) < 0.85 * expected:
            out.append({"kind": "count", "level": "watch",
                        "text": f"At most {today['birds_max']} of {expected} birds were visible today. "
                                "Birds may be out of view, or missing. Worth a head count."})
        if today.get("coverage_h", 0) < 12:
            out.append({"kind": "coverage", "level": "watch",
                        "text": f"The camera saw only {today['coverage_h']} hours today. "
                                "Check the coop phone's power and signal."})
    if not out and today.get("readings"):
        out.append({"kind": "ok", "level": "ok", "text": "Water, feed and comfort all held steady today."})
    return out


def week(coop: dict, days: int = 7) -> dict:
    coop_id = coop["id"]
    now = store.now()
    local_now = store.local(now)
    start = (local_now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    hours = timeline.hours_between(coop_id, start, now)
    by_day: dict[str, list[dict]] = defaultdict(list)
    for h in hours:
        by_day[h["hour"][:8]].append(h)

    day_keys = [(start + timedelta(days=i)).strftime("%Y%m%d") for i in range(days)]
    per_day = [{"day": k, **_day(by_day.get(k, []))} for k in day_keys]
    grid = []
    for k in day_keys:
        lookup = {h["hour"][8:10]: h for h in by_day.get(k, [])}
        grid.append({"day": k, "hours": [cell(lookup.get(f"{i:02d}")) for i in range(24)]})

    alarms_q = (store.coop_ref(coop_id).collection("alarms")
                .where(filter=firestore.FieldFilter("ts", ">=", start.astimezone(now.tzinfo))))
    alarms = [a.to_dict() for a in alarms_q.stream()]
    answer_min = [(a["answered_at"] - a["ts"]).total_seconds() / 60 for a in alarms if a.get("answered_at")]
    calls_q = (store.coop_ref(coop_id).collection("calls")
               .where(filter=firestore.FieldFilter("ts", ">=", start.astimezone(now.tzinfo))))
    calls = [c.to_dict() for c in calls_q.stream()]

    created: datetime | None = coop.get("created")
    age = (coop.get("age_days_at_start") or 0) + ((now - created).days if created else 0)
    today = per_day[-1]
    return {
        "days": per_day,
        "grid": grid,
        "today": today,
        "insights": insights(coop, [by_day.get(k, []) for k in day_keys], today),
        "flock": {"expected": coop.get("birds_expected"), "age_days": age, "week_of_life": age // 7 + 1},
        "alarms": {
            "count": len(alarms),
            "by_kind": dict(Counter(a["kind"] for a in alarms)),
            "unanswered": sum(1 for a in alarms if a.get("status") == "ringing"),
            "median_answer_min": round(median(answer_min), 1) if answer_min else None,
        },
        "calls": {"count": len(calls), "minutes": round(sum(c.get("duration_s", 0) for c in calls) / 60, 1)},
        "care_weights": CARE_WEIGHTS,
    }
