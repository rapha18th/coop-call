"""One path for every picture, whether it comes from a phone, a camera, or a video feed."""

from __future__ import annotations

import logging
import time

from . import alarms, config, device, infer, store, timeline, vision

log = logging.getLogger("coop.pipeline")
_last_vision: dict[str, float] = {}


def _num(v) -> float | None:
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def sensor_obs(sensors: dict, ts) -> dict:
    return {
        "ts": ts, "source": "sensor", "simulated": False,
        "brightness": _num(sensors.get("brightness")), "sound_db": _num(sensors.get("sound_db")),
        "motion": _num(sensors.get("motion")), "battery": _num(sensors.get("battery")),
        "charging": bool(sensors.get("charging")),
    }


def ingest(coop_id: str, jpeg: bytes | None, readings: dict, force: bool = False) -> dict:
    """Record the readings, and read the picture if enough time has passed since the last one."""
    ts = store.now()
    timeline.record(coop_id, sensor_obs(readings, ts))
    device.record_beat(coop_id, readings)
    if jpeg is None:
        return {"analysed": False}
    since = time.time() - _last_vision.get(coop_id, 0)
    if not force and since < config.MIN_VISION_INTERVAL_S:
        return {"analysed": False, "wait_s": round(config.MIN_VISION_INTERVAL_S - since)}
    _last_vision[coop_id] = time.time()
    path = store.save_frame(coop_id, ts, jpeg)
    try:
        seen = vision.read_frame(jpeg)
    except Exception as exc:
        log.exception("vision failed")
        device.record_frame(coop_id, False, str(exc))
        return {"analysed": False, "error": str(exc)[:200]}
    device.record_frame(coop_id, True)
    store.bump_usage(frames=1)
    timeline.record(coop_id, {"ts": ts, "source": "vision", "simulated": False, "frame": path, **seen})
    alarms.evaluate(coop_id)
    infer.flock_if_missing(coop_id)
    return {"analysed": True, "seen": seen}
