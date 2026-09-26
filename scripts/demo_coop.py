"""Create the public demo coop, and optionally give it a simulated history.

    python scripts/demo_coop.py --owner-uid <your Firebase uid> [--simulate-hours 30]

Simulated observations are flagged simulated=True end to end: the dashboard shows
a "demo data" badge and the agent is told. Live readings from a paired phone are real.
"""

import argparse
import random
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from app import config, store, timeline  # noqa: E402


def reset(coop_id: str) -> None:
    ref = store.coop_ref(coop_id)
    for name in ("obs", "hours", "alarms"):
        docs = list(ref.collection(name).list_documents())
        for i in range(0, len(docs), 400):
            batch = store.db().batch()
            for d in docs[i:i + 400]:
                batch.delete(d)
            batch.commit()


def simulate(coop_id: str, hours: int, birds: int) -> None:
    rng = random.Random(7)
    ref = store.coop_ref(coop_id)
    rollups: dict[str, dict] = {}
    rows: list[dict] = []

    def add(obs: dict) -> None:
        rows.append(obs)
        key = store.hour_key(obs["ts"])
        rollups[key] = timeline.fold(rollups.get(key), obs)

    t = store.now() - timedelta(hours=hours)
    while t < store.now() - timedelta(minutes=30):
        lt = store.local(t)
        night = lt.hour >= 19 or lt.hour < 6
        # One cold spell before dawn, and a dry drinker mid-afternoon yesterday.
        cold = lt.hour in (2, 3) and rng.random() < 0.8
        dry = lt.hour == 15 and 5 <= lt.minute <= 45
        obs = {
            "ts": t, "source": "vision", "simulated": True, "frame": None,
            "birds": birds - rng.randint(0, 3),
            "spread": "huddled" if cold else ("crowded_drinker" if dry else "even"),
            "activity": "resting" if night else rng.choice(["calm", "active"]),
            "panting": lt.hour in (13, 14) and rng.random() < 0.3,
            "feeder": "low" if lt.hour in (5, 6) else rng.choice(["full", "half"]),
            "drinker": "empty" if dry else rng.choice(["full", "half"]),
            "lights": "on" if night else "daylight",
            "unusual": "", "summary": "Simulated reading.",
        }
        add(obs)
        add({
            "ts": t, "source": "sensor", "simulated": True,
            "brightness": 40.0 if night else 150.0 + rng.random() * 30,
            "sound_db": (38 if night else 52) + rng.random() * 6,
            "motion": 1 + rng.random() * (2 if night else 8),
            "battery": 0.9, "charging": True,
        })
        t += timedelta(minutes=10)

    for i in range(0, len(rows), 400):
        batch = store.db().batch()
        for obs in rows[i:i + 400]:
            batch.set(ref.collection("obs").document(), obs)
        batch.commit()
    batch = store.db().batch()
    for key, h in rollups.items():
        batch.set(ref.collection("hours").document(key), h)
    batch.commit()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--owner-uid", required=True)
    p.add_argument("--name", default="The Hen House")
    p.add_argument("--birds", type=int, default=48)
    p.add_argument("--simulate-hours", type=int, default=0)
    a = p.parse_args()
    reset(config.DEMO_COOP_ID)
    coop, key = store.create_coop(a.owner_uid, a.name, "the owner", a.birds, 21, coop_id=config.DEMO_COOP_ID)
    print(f"demo coop '{coop['id']}' ready")
    print(f"pair the coop phone: {config.WEB_URL}/node/{coop['id']}#{key}")
    if a.simulate_hours:
        simulate(coop["id"], a.simulate_hours, a.birds)
        print(f"added {a.simulate_hours} hours of simulated history")


if __name__ == "__main__":
    main()
