"""The coop's memory: observations, hourly rollups, and the answers built on them."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from google.cloud import firestore

from . import config, store

LOW = {"low", "empty"}


def _obs(coop_id: str):
    return store.coop_ref(coop_id).collection("obs")


def _hours(coop_id: str):
    return store.coop_ref(coop_id).collection("hours")


# ------------------------------------------------------------------ writing


def record(coop_id: str, obs: dict) -> dict:
    """Store one observation and fold it into its hour."""
    ts: datetime = obs["ts"]
    _obs(coop_id).add(obs)
    ref = _hours(coop_id).document(store.hour_key(ts))
    _fold(store.db().transaction(), ref, obs)
    store.coop_ref(coop_id).update({"last_seen": ts})
    return obs


@firestore.transactional
def _fold(tx, ref, obs: dict) -> None:
    snap = ref.get(transaction=tx)
    tx.set(ref, fold(snap.to_dict() if snap.exists else None, obs))


def fold(h: dict | None, obs: dict) -> dict:
    """Add one observation to an hour's rollup. Pure, so batch writers can reuse it."""
    h = dict(h) if h else {"hour": store.hour_key(obs["ts"]), "n": 0, "nv": 0}
    h["n"] += 1
    h["last_ts"] = obs["ts"]
    h.setdefault("first_ts", obs["ts"])
    if obs.get("simulated"):
        h["simulated"] = True
    for key in ("brightness", "sound_db", "motion", "temperature_c", "humidity_pct", "ammonia_ppm"):
        if obs.get(key) is not None:
            h[f"{key}_sum"] = h.get(f"{key}_sum", 0.0) + float(obs[key])
            h[f"{key}_n"] = h.get(f"{key}_n", 0) + 1
    if obs.get("source") == "vision":
        h["nv"] += 1
        birds = int(obs.get("birds") or 0)
        h["birds_sum"] = h.get("birds_sum", 0) + birds
        h["birds_min"] = min(h.get("birds_min", birds), birds)
        h["birds_max"] = max(h.get("birds_max", birds), birds)
        for flag, hit in (
            ("huddled", obs.get("spread") == "huddled"),
            ("hot_spread", obs.get("spread") in ("clustered_edges", "avoiding_area")),
            ("panting", bool(obs.get("panting"))),
            ("agitated", obs.get("activity") == "agitated"),
            ("feeder_low", obs.get("feeder") in LOW),
            ("drinker_low", obs.get("drinker") in LOW),
            ("drinker_empty", obs.get("drinker") == "empty"),
            ("feeder_empty", obs.get("feeder") == "empty"),
            ("lights_off", obs.get("lights") == "off"),
        ):
            if hit:
                h[flag] = h.get(flag, 0) + 1
        if obs.get("frame"):
            h["frame"] = obs["frame"]
        if obs.get("unusual"):
            notes = list(h.get("notes", []))
            notes.append({"ts": obs["ts"], "text": obs["unusual"], "frame": obs.get("frame")})
            h["notes"] = notes[-5:]
    return h


# ------------------------------------------------------------------ reading


def latest(coop_id: str, source: str | None = None) -> dict | None:
    q = _obs(coop_id)
    if source:
        q = q.where(filter=firestore.FieldFilter("source", "==", source))
    q = q.order_by("ts", direction=firestore.Query.DESCENDING).limit(1)
    docs = list(q.stream())
    return docs[0].to_dict() if docs else None


def recent(coop_id: str, n: int, source: str = "vision") -> list[dict]:
    q = (_obs(coop_id).where(filter=firestore.FieldFilter("source", "==", source))
         .order_by("ts", direction=firestore.Query.DESCENDING).limit(n))
    return [d.to_dict() for d in q.stream()]


def hours_between(coop_id: str, start: datetime, end: datetime) -> list[dict]:
    q = (_hours(coop_id)
         .where(filter=firestore.FieldFilter("hour", ">=", store.hour_key(start)))
         .where(filter=firestore.FieldFilter("hour", "<=", store.hour_key(end)))
         .order_by("hour"))
    return [d.to_dict() for d in q.stream()]


def near(coop_id: str, ts: datetime, window_min: int = 45) -> dict | None:
    """The vision observation with a frame closest to ts."""
    q = (_obs(coop_id)
         .where(filter=firestore.FieldFilter("ts", ">=", ts - timedelta(minutes=window_min)))
         .where(filter=firestore.FieldFilter("ts", "<=", ts + timedelta(minutes=window_min)))
         .order_by("ts"))
    best = None
    for d in q.stream():
        o = d.to_dict()
        if o.get("source") != "vision" or not o.get("frame"):
            continue
        if best is None or abs(o["ts"] - ts) < abs(best["ts"] - ts):
            best = o
    return best


# ------------------------------------------------------------------ words


def clock(ts: datetime) -> str:
    return store.local(ts).strftime("%H:%M")


def ago(ts: datetime) -> str:
    s = int((store.now() - ts).total_seconds())
    if s < 90:
        return f"{s} seconds ago"
    if s < 5400:
        return f"{s // 60} minutes ago"
    return f"{s // 3600} hours ago"


def describe_obs(o: dict) -> str:
    parts = [f"{o.get('birds', '?')} birds visible", f"flock {o.get('spread', 'unclear').replace('_', ' ')}",
             f"{o.get('activity', 'unclear')}"]
    if o.get("panting"):
        parts.append("some panting")
    for thing in ("feeder", "drinker"):
        level = o.get(thing)
        if level and level != "not_visible":
            parts.append(f"{thing} {level}")
    if o.get("lights") in ("on", "off"):
        parts.append(f"lights {o['lights']}")
    text = ", ".join(parts) + "."
    if o.get("unusual"):
        text += f" Unusual: {o['unusual']}"
    return text


def _frac(h: dict, key: str) -> float:
    return h.get(key, 0) / h["nv"] if h.get("nv") else 0.0


def _mean(h: dict, key: str) -> float | None:
    n = h.get(f"{key}_n", 0)
    return h[f"{key}_sum"] / n if n else None


def describe_hour(h: dict) -> str:
    hh = h["hour"][8:10] + ":00"
    if not h.get("nv"):
        extra = ""
        s = _mean(h, "sound_db")
        if s is not None:
            extra = f", sound level {s:.0f} of 100"
        return f"{hh} no camera reading{extra}."
    birds = round(h["birds_sum"] / h["nv"])
    bits = [f"{hh} about {birds} birds"]
    for key, words in (("huddled", "huddled"), ("hot_spread", "keeping to the edges"),
                       ("panting", "panting"), ("agitated", "agitated"),
                       ("drinker_low", "drinker low"), ("feeder_low", "feeder low"),
                       ("lights_off", "lights off")):
        f = _frac(h, key)
        if f >= 0.2:
            bits.append(f"{words} {round(f * 100)}% of checks")
    s = _mean(h, "sound_db")
    if s is not None:
        bits.append(f"sound level {s:.0f} of 100")
    t = _mean(h, "temperature_c")
    if t is not None:
        bits.append(f"{t:.1f} °C")
    rh = _mean(h, "humidity_pct")
    if rh is not None:
        bits.append(f"humidity {rh:.0f}%")
    nh3 = _mean(h, "ammonia_ppm")
    if nh3 is not None:
        bits.append(f"ammonia {nh3:.0f} ppm")
    line = ", ".join(bits) + "."
    for n in h.get("notes", [])[-2:]:
        line += f" At {clock(n['ts'])}: {n['text']}"
    return line


# ------------------------------------------------------------------ tool answers


def answer_now(coop_id: str) -> dict:
    v = latest(coop_id, "vision")
    s = latest(coop_id, "sensor")
    out: dict = {"local_time": store.local(store.now()).strftime("%A %H:%M")}
    if v:
        out["camera"] = f"{describe_obs(v)} (seen {ago(v['ts'])})"
        out["frame_url"] = store.frame_url(v.get("frame"))
        out["frame_time"] = clock(v["ts"])
        if v.get("simulated"):
            out["note"] = "demo data"
    else:
        out["camera"] = "No camera reading yet."
    if s:
        sense = []
        if s.get("sound_db") is not None:
            sense.append(f"sound level {s['sound_db']:.0f} of 100")
        if s.get("brightness") is not None:
            sense.append(f"brightness {s['brightness']:.0f} of 255")
        if s.get("temperature_c") is not None:
            sense.append(f"{s['temperature_c']:.1f} °C")
        if s.get("humidity_pct") is not None:
            sense.append(f"humidity {s['humidity_pct']:.0f}%")
        if s.get("ammonia_ppm") is not None:
            sense.append(f"ammonia {s['ammonia_ppm']:.0f} ppm")
        if s.get("battery") is not None:
            sense.append(f"coop phone battery {round(s['battery'] * 100)}%"
                         + (" charging" if s.get("charging") else " not charging"))
        out["sensors"] = ", ".join(sense) + f" ({ago(s['ts'])})."
    return out


def answer_period(coop_id: str, start: datetime, end: datetime) -> dict:
    hours = hours_between(coop_id, start, end)
    if not hours:
        return {"period": f"{clock(start)} to {clock(end)}", "summary": "No readings in that period."}
    lines = [describe_hour(h) for h in hours]
    notes = [n for h in hours for n in h.get("notes", [])]
    key = notes[-1] if notes else None
    frame = key["frame"] if key and key.get("frame") else hours[-1].get("frame")
    return {
        "period": f"{store.local(start).strftime('%a %H:%M')} to {store.local(end).strftime('%a %H:%M')}",
        "hours": lines[-24:],
        "frame_url": store.frame_url(frame),
        "demo_data": any(h.get("simulated") for h in hours),
    }


def baseline(coop_id: str, ts: datetime, days: int = 7) -> list[dict]:
    keys = [store.hour_key(ts - timedelta(days=d)) for d in range(1, days + 1)]
    refs = [_hours(coop_id).document(k) for k in keys]
    return [s.to_dict() for s in store.db().get_all(refs) if s.exists]


def answer_vs_normal(coop_id: str) -> dict:
    t = store.now()
    cur = _hours(coop_id).document(store.hour_key(t)).get()
    if not cur.exists or not cur.to_dict().get("nv"):
        return {"comparison": "Not enough readings this hour yet."}
    h = cur.to_dict()
    past = [p for p in baseline(coop_id, t) if p.get("nv")]
    if len(past) < 2:
        return {"comparison": "Fewer than two earlier days at this hour, so there is no normal yet.",
                "this_hour": describe_hour(h)}
    findings = []
    for label, fn in (
        ("birds visible", lambda x: x["birds_sum"] / x["nv"]),
        ("share of checks huddled", lambda x: _frac(x, "huddled")),
        ("share of checks agitated", lambda x: _frac(x, "agitated")),
        ("share of checks with a low drinker", lambda x: _frac(x, "drinker_low")),
    ):
        vals = [fn(p) for p in past]
        mean = sum(vals) / len(vals)
        sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals)) or max(abs(mean) * 0.15, 0.05)
        z = (fn(h) - mean) / sd
        if abs(z) >= 1.5:
            findings.append(f"{label} is {'higher' if z > 0 else 'lower'} than usual for this hour "
                            f"({fn(h):.2f} against a usual {mean:.2f})")
    return {
        "this_hour": describe_hour(h),
        "days_compared": len(past),
        "comparison": "; ".join(findings) if findings else "Everything is within the usual range for this hour.",
    }


def answer_frame(coop_id: str, ts: datetime | None) -> dict:
    o = latest(coop_id, "vision") if ts is None else near(coop_id, ts)
    if not o or not o.get("frame"):
        return {"found": False, "note": "No picture near that time."}
    return {
        "found": True,
        "time": clock(o["ts"]),
        "frame_url": store.frame_url(o["frame"]),
        "description": describe_obs(o),
    }


def parse_local(value: str | None) -> datetime | None:
    if not value or value == "now":
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=config.TZ)
    return dt
