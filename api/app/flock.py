"""The broiler business: where the flock is, what it costs, when to sell, what to do today.

Growth and feed targets come from the Cobb500 Broiler Performance & Nutrition
Supplement (2022, metric, as hatched). Default prices are Zimbabwe figures from
September 2026 and every one of them is editable per flock.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from google.cloud import firestore

from . import store

DATA = Path(__file__).parent / "data" / "cobb500.json"

DEFAULT_PRICES = {
    "chick": 0.90,          # USD per day-old chick; USD 0.45 to 1.10 seen in 2026
    "feed_per_kg": 0.62,    # USD; a 50 kg bag at about USD 28 to 34
    "sell_per_kg": 2.10,    # USD live weight; Harare live market 2.10 to 2.30, processors 2.00 to 2.10
    "other_per_bird": 1.00, # USD; medication, litter, labour, utilities
}
# Zimbabwe farms commonly sell at about 2.4 kg on day 42 against a Cobb500 target of 3.28 kg.
DEFAULT_GROWTH_FACTOR = 0.75
BAG_KG = 50

PHASES = [("Starter", 0, 12), ("Grower", 13, 28), ("Finisher", 29, 99)]

VACCINES = [
    (7, "Newcastle disease vaccine in the drinking water"),
    (14, "Gumboro (IBD) vaccine in the drinking water"),
    (21, "Newcastle booster in the drinking water"),
]


@lru_cache
def curve() -> list[dict]:
    return json.loads(DATA.read_text(encoding="utf-8"))["days"]


def target(day: int) -> dict:
    days = curve()
    return days[max(0, min(day, len(days) - 1))]


def phase(day: int) -> tuple[str, int, int]:
    for name, a, b in PHASES:
        if a <= day <= b:
            return name, a, b
    return PHASES[-1]


def brooding_temp(day: int) -> str:
    if day <= 7:
        return "32 to 35°C at chick level"
    if day <= 14:
        return "29 to 32°C"
    if day <= 21:
        return "26 to 29°C"
    return "21 to 26°C, keep air moving on hot days"


# ------------------------------------------------------------------ records


def _flock_doc(coop_id: str):
    return store.coop_ref(coop_id)


def ledger(coop_id: str, batch: str) -> list[dict]:
    q = (store.coop_ref(coop_id).collection("ledger")
         .where(filter=firestore.FieldFilter("batch", "==", batch)))
    rows = [{"id": d.id, **d.to_dict()} for d in q.stream()]
    return sorted(rows, key=lambda r: r["ts"])


KINDS = {"feed_bought", "deaths", "sold", "weighed", "expense", "vaccinated", "note"}


def add_record(coop_id: str, batch: str, kind: str, quantity: float | None, amount: float | None,
               note: str, by: str | None, unit: str = "") -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}")
    row = {"ts": store.now(), "batch": batch, "kind": kind, "quantity": quantity, "unit": unit,
           "amount_usd": amount, "note": note[:300], "by": by}
    ref = store.coop_ref(coop_id).collection("ledger").document()
    ref.set(row)
    return {"id": ref.id, **row}


def setup(coop_id: str, birds: int, age_days: int, breed: str, prices: dict, sell_day: int,
          growth_factor: float | None = None) -> dict:
    placed = (store.local(store.now()).date() - timedelta(days=age_days)).isoformat()
    batch = f"b{placed.replace('-', '')}"
    flock = {
        "batch": batch, "placed": placed, "birds_placed": birds, "breed": breed,
        "prices": {**DEFAULT_PRICES, **{k: float(v) for k, v in prices.items() if v is not None}},
        "sell_day": sell_day, "growth_factor": growth_factor, "status": "growing",
    }
    _flock_doc(coop_id).update({"flock": flock, "birds_expected": birds})
    existing = ledger(coop_id, batch)
    if not any(r["kind"] == "expense" and r.get("note") == "Day-old chicks" for r in existing):
        add_record(coop_id, batch, "expense", birds, round(birds * flock["prices"]["chick"], 2),
                   "Day-old chicks", None, "chicks")
    return flock


# ------------------------------------------------------------------ the model


def _age(flock: dict, today: date | None = None) -> int:
    today = today or store.local(store.now()).date()
    return max(0, (today - date.fromisoformat(flock["placed"])).days)


def state(coop: dict) -> dict | None:
    flock = coop.get("flock")
    if not flock:
        return None
    coop_id = coop["id"]
    rows = ledger(coop_id, flock["batch"])
    p = flock["prices"]
    age = _age(flock)
    placed = flock["birds_placed"]
    deaths = sum(r.get("quantity") or 0 for r in rows if r["kind"] == "deaths")
    sold = sum(r.get("quantity") or 0 for r in rows if r["kind"] == "sold")
    alive = max(0, placed - deaths - sold)
    t = target(age)

    # Growth: the latest weigh-in sets how this flock compares with the breed curve.
    weighs = [r for r in rows if r["kind"] == "weighed" and r.get("quantity")]
    factor, measured = flock.get("growth_factor") or DEFAULT_GROWTH_FACTOR, None
    factor_source = "typical Zimbabwe farm"
    if weighs:
        w = weighs[-1]
        w_age = _age(flock, store.local(w["ts"]).date())
        measured = {"kg": w["quantity"], "day": w_age, "target_kg": round(target(w_age)["weight_g"] / 1000, 2)}
        if w_age >= 7:
            factor = w["quantity"] * 1000 / target(w_age)["weight_g"]
            factor_source = f"your weigh-in on day {w_age}"
    est_kg = t["weight_g"] * factor / 1000

    # Feed: what the birds should have eaten against what was bought.
    bought_kg = sum((r.get("quantity") or 0) for r in rows if r["kind"] == "feed_bought")
    eaten_kg = sum(target(d)["feed_g"] or 0 for d in range(1, age + 1)) * alive / 1000
    on_hand = bought_kg - eaten_kg
    today_kg = (target(age + 1)["feed_g"] or 0) * alive / 1000
    days_left = None
    if bought_kg:
        days_left, left = 0, on_hand
        while days_left < 60:
            need = (target(age + 1 + days_left)["feed_g"] or 0) * alive / 1000
            if left < need:
                break
            left -= need
            days_left += 1

    # Money so far. Records sharpen it; without them the model estimates what the birds have eaten.
    spent = sum((r.get("amount_usd") or 0) for r in rows if r["kind"] in ("feed_bought", "expense"))
    income = sum((r.get("amount_usd") or 0) for r in rows if r["kind"] == "sold")
    feed_logged = sum((r.get("amount_usd") or 0) for r in rows if r["kind"] == "feed_bought")
    feed_est = eaten_kg * p["feed_per_kg"]
    chicks = sum((r.get("amount_usd") or 0) for r in rows if r["kind"] == "expense" and r.get("note") == "Day-old chicks")
    extras = sum((r.get("amount_usd") or 0) for r in rows if r["kind"] == "expense") - chicks
    other_est = p["other_per_bird"] * placed * min(age, 40) / 40
    cost_so_far = chicks + max(feed_logged, feed_est) + max(other_est, extras)

    plan = sell_plan(flock, alive, age, factor, spent, income, bought_kg, eaten_kg)
    best = max(plan, key=lambda r: r["margin"]) if plan else None
    chosen = next((r for r in plan if r["day"] == flock.get("sell_day")), best)

    weekly = []
    for wk in range(1, 8):
        a, b = (wk - 1) * 7, wk * 7
        kg_bird = (target(b)["cum_feed_g"] - target(a)["cum_feed_g"]) / 1000
        weekly.append({"week": wk, "kg_per_bird": round(kg_bird, 2), "kg": round(kg_bird * alive),
                       "usd": round(kg_bird * alive * p["feed_per_kg"]),
                       "bags": round(kg_bird * alive / BAG_KG, 1), "now": a < age + 1 <= b})
    horizon = max(flock.get("sell_day") or 35, 30)
    batch_feed = target(horizon)["cum_feed_g"]
    last_two = (batch_feed - target(horizon - 14)["cum_feed_g"]) / batch_feed

    name, _, end = phase(age)
    return {
        "batch": flock["batch"], "placed": flock["placed"], "breed": flock.get("breed", "Cobb 500"),
        "inferred": bool(flock.get("inferred")),
        "age_days": age, "week": age // 7 + 1, "phase": name,
        "phase_ends_in": end - age if end < 99 else None,
        "next_phase": phase(end + 1)[0] if end < 99 else None,
        "birds": {"placed": placed, "alive": alive, "deaths": deaths, "sold": sold,
                  "mortality_pct": round(100 * deaths / placed, 1) if placed else 0},
        "growth": {"target_kg": round(t["weight_g"] / 1000, 2), "estimate_kg": round(est_kg, 2),
                   "factor": round(factor, 2), "factor_source": factor_source, "measured": measured,
                   "curve": [{"day": d["day"], "target_kg": round(d["weight_g"] / 1000, 3)}
                             for d in curve() if d["day"] <= max(horizon, age) + 3],
                   "weighs": [{"day": _age(flock, store.local(r["ts"]).date()), "kg": r["quantity"]}
                              for r in weighs]},
        "feed": {"today_kg": round(today_kg, 1), "today_bags": round(today_kg / BAG_KG, 2),
                 "per_bird_g": target(age + 1)["feed_g"], "bought_kg": round(bought_kg),
                 "eaten_kg": round(eaten_kg), "on_hand_kg": round(on_hand) if bought_kg else None,
                 "days_left": days_left, "weekly": weekly,
                 "last_two_weeks_share": round(last_two * 100), "sell_day": horizon,
                 "last_two_weeks_usd": round((batch_feed - target(max(age, horizon - 14))["cum_feed_g"])
                                             / 1000 * alive * p["feed_per_kg"]) if age < horizon else 0},
        "water_l_today": round(today_kg * 1.8, 1),
        "money": {"spent": round(spent, 2), "income": round(income, 2),
                  "cost_so_far": round(cost_so_far), "estimated": not feed_logged,
                  "cost_per_bird_so_far": round(cost_so_far / placed, 2) if placed else None,
                  "plan": plan, "best_day": best["day"] if best else None,
                  "chosen": chosen, "prices": p},
        "tasks": tasks(age, rows, days_left),
    }


def sell_plan(flock: dict, alive: int, age: int, factor: float, spent: float, income: float,
              bought_kg: float, eaten_kg: float) -> list[dict]:
    """Projected margin for selling on each day from 30 to 45.

    Feed already bought is in spent; the plan only adds feed still to buy. Other costs
    (medication, litter, labour) accrue per bird per day over a 40-day batch unless logged.
    """
    p = flock["prices"]
    other_per_day = p["other_per_bird"] / 40
    out = []
    for day in range(max(30, age), 50):
        weight = target(day)["weight_g"] * factor / 1000
        feed_left = (target(day)["cum_feed_g"] - target(age)["cum_feed_g"]) / 1000 * alive
        to_buy = max(0.0, eaten_kg + feed_left - bought_kg)
        revenue = alive * weight * p["sell_per_kg"]
        other = flock["birds_placed"] * other_per_day * day
        margin = revenue + income - spent - to_buy * p["feed_per_kg"] - other
        gain = (target(day)["gain_g"] or 0) * factor / 1000 * p["sell_per_kg"]
        eat = (target(day)["feed_g"] or 0) / 1000 * p["feed_per_kg"]
        out.append({"day": day, "weight_kg": round(weight, 2), "revenue": round(revenue),
                    "feed_to_buy": round(to_buy * p["feed_per_kg"]), "margin": round(margin),
                    "margin_per_bird": round(margin / alive, 2) if alive else None,
                    "extra_day_value": round(gain - eat, 3)})
    return out


def tasks(age: int, rows: list[dict], feed_days_left: int | None) -> list[dict]:
    notes = [(r.get("note") or "").lower() for r in rows if r["kind"] == "vaccinated"]
    nd = sum(1 for n in notes if "newcastle" in n or "nd" in n.split())
    ibd = sum(1 for n in notes if "gumboro" in n or "ibd" in n)
    done = {7: nd >= 1, 14: ibd >= 1, 21: nd >= 2}
    out = []
    for day, text in VACCINES:
        if done[day]:
            continue
        if day - 2 <= age <= day + 6:
            when = "today" if age == day else f"in {day - age} days" if age < day else f"{age - day} days overdue"
            out.append({"when": when, "kind": "vaccine",
                        "text": f"Day {day}: {text}. Confirm the product with your chick supplier or vet."})
    name, _, end = phase(age)
    if end < 99 and end - age <= 3:
        out.append({"when": f"in {end - age + 1} days", "kind": "feed",
                    "text": f"Switch from {name.lower()} to {phase(end + 1)[0].lower()} feed on day {end + 1}. Mix the two for two days."})
    if feed_days_left is not None and feed_days_left <= 5:
        out.append({"when": "now", "kind": "feed",
                    "text": f"Feed on hand lasts about {feed_days_left} days at the current appetite. Buy more."})
    if age % 7 == 0 and age > 0:
        out.append({"when": "today", "kind": "weigh",
                    "text": "Weigh ten birds and tell the coop the average. It sharpens every projection."})
    out.append({"when": "daily", "kind": "heat", "text": f"Brooding temperature: {brooding_temp(age)}."})
    out.append({"when": "daily", "kind": "light",
                "text": "Light nearly all day for the first week. After that, give at least four hours of dark each night."})
    return out


def money(v, places: int = 0) -> str:
    if v is None:
        return "unknown"
    return ("minus " if v < 0 else "") + f"${abs(v):,.{places}f}"


def briefing(s: dict | None) -> str:
    """One paragraph the voice agent starts every call with."""
    if not s:
        return "The flock has not been set up, so there are no business numbers yet."
    m, f, g, b = s["money"], s["feed"], s["growth"], s["birds"]
    ch = m.get("chosen") or {}
    due = " ".join(f"{t['text']} ({t['when']})." for t in s["tasks"] if t["when"] != "daily")
    origin = ("The flock size and age were estimated from the camera, not entered by the owner. "
              if s.get("inferred") else "")
    on_hand = f"; feed on hand lasts about {f['days_left']} days" if f["days_left"] is not None else ""
    cost_note = " (estimated from what the birds should have eaten)" if m["estimated"] else ""
    return (
        f"{origin}Flock: day {s['age_days']} (week {s['week']}), {s['phase']} feed, {b['alive']} of "
        f"{b['placed']} birds ({b['mortality_pct']}% lost). Estimated weight {g['estimate_kg']} kg against a "
        f"breed target of {g['target_kg']} kg, based on {g['factor_source']}. Feed today about "
        f"{f['today_kg']} kg ({f['today_bags']} bags){on_hand}. Cost so far about "
        f"{money(m['cost_so_far'])}{cost_note}. If sold on day {ch.get('day')}, projected margin "
        f"{money(ch.get('margin'))} ({money(ch.get('margin_per_bird'), 2)} a bird); the model's best day is "
        f"{m['best_day']}. The last two weeks before selling eat {f['last_two_weeks_share']}% of the batch's "
        f"feed, about {money(f['last_two_weeks_usd'])} still to buy for them. Due: {due or 'nothing urgent.'} "
        "Records are optional: never ask the owner to enter anything, work from what you see."
    )
