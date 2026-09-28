"""What the coop can work out on its own, so records stay optional."""

from __future__ import annotations

from statistics import median

from . import flock, store, timeline

MIN_READINGS = 5


def flock_if_missing(coop_id: str) -> dict | None:
    """With no flock set up, estimate one from what the camera sees: size from the most birds
    in view, age from how they look. The owner can correct it at any time."""
    coop = store.get_coop(coop_id)
    if not coop or coop.get("flock"):
        return None
    seen = timeline.recent(coop_id, 30)
    if len(seen) < MIN_READINGS:
        return None
    ages = [o["age_days"] for o in seen if o.get("age_days")]
    counts = sorted(o.get("birds") or 0 for o in seen)
    if not ages or not counts[-1]:
        return None
    birds = counts[int(0.9 * (len(counts) - 1))]
    age = int(median(ages))
    f = flock.setup(coop_id, birds, min(age, 70), "Cobb 500", {}, 35)
    store.coop_ref(coop_id).update({"flock.inferred": True, "flock.inferred_from": len(seen)})
    return f


def birds_in_view(coop_id: str) -> int | None:
    seen = timeline.recent(coop_id, 20)
    counts = [o.get("birds") or 0 for o in seen]
    return max(counts) if counts else None
