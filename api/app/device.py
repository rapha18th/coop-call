"""The coop phone's own health: is it alive, charged, connected, and can it see."""

from __future__ import annotations

from datetime import datetime

from google.cloud import firestore

from . import config, store

APP_VERSION = "0.3"


def record_beat(coop_id: str, sensors: dict) -> None:
    now = store.now()
    update = {"device.last_beat": now}
    for key in ("battery", "charging", "network", "sharpness", "brightness", "width", "height",
                "version", "camera", "mic", "temperature_c", "humidity_pct", "ammonia_ppm"):
        if sensors.get(key) is not None:
            update[f"device.{key}"] = sensors[key]
    store.coop_ref(coop_id).update(update)


def record_frame(coop_id: str, ok: bool, error: str = "") -> None:
    update: dict = {"device.last_frame": store.now(), "device.frames": firestore.Increment(1)}
    if ok:
        update["device.last_vision_ok"] = store.now()
    else:
        update["device.vision_errors"] = firestore.Increment(1)
        update["device.last_error"] = error[:160]
    store.coop_ref(coop_id).update(update)


def _ago_s(ts: datetime | None) -> float | None:
    return (store.now() - ts).total_seconds() if ts else None


def health(coop: dict) -> dict:
    d = coop.get("device") or {}
    beat = _ago_s(d.get("last_beat"))
    frame = _ago_s(d.get("last_frame"))
    checks = []

    def check(name: str, level: str, text: str) -> None:
        checks.append({"name": name, "level": level, "text": text})

    if beat is None:
        check("link", "down", "No coop phone has reported yet.")
    elif beat > config.NODE_SILENT_AFTER_S:
        check("link", "down", f"Silent for {int(beat // 60)} minutes.")
    else:
        net = d.get("network")
        check("link", "ok", f"Online{f' on {net}' if net else ''}, last heard {int(beat)} s ago.")

    batt, charging = d.get("battery"), d.get("charging")
    if batt is not None:
        pct = round(batt * 100)
        if charging:
            check("power", "ok", f"{pct}%, charging.")
        elif pct < 20:
            check("power", "down", f"{pct}% and not charging.")
        elif pct < 50:
            check("power", "warn", f"{pct}% and not charging.")
        else:
            check("power", "ok", f"{pct}%, on battery.")

    bright, sharp = d.get("brightness"), d.get("sharpness")
    if d.get("camera") == "off":
        check("camera", "down", "Camera is off.")
    elif bright is not None and bright < 18:
        check("camera", "warn", "Too dark to see. Add a light or move the phone.")
    elif sharp is not None and sharp < 4:
        check("camera", "warn", "View looks blurred or blocked. Wipe the lens.")
    elif frame is not None and frame > 600 and beat is not None and beat < 120:
        check("camera", "warn", f"No picture for {int(frame // 60)} minutes.")
    elif bright is not None:
        check("camera", "ok", "Clear view.")

    t, rh, nh3 = d.get("temperature_c"), d.get("humidity_pct"), d.get("ammonia_ppm")
    if t is not None or rh is not None or nh3 is not None:
        parts = [f"{t:.1f} °C" if t is not None else None, f"{rh:.0f}% humidity" if rh is not None else None,
                 f"{nh3:.0f} ppm ammonia" if nh3 is not None else None]
        level = "warn" if (nh3 is not None and nh3 >= 25) else "ok"
        check("air", level, ", ".join(p for p in parts if p) + (". Ammonia above 25 ppm; ventilate." if level == "warn" else "."))

    errs = d.get("vision_errors", 0)
    ok_at = _ago_s(d.get("last_vision_ok"))
    if frame is not None and (ok_at is None or ok_at > 900) and errs:
        check("vision", "warn", f"Pictures arrive but reading them failed {errs} times.")
    elif ok_at is not None:
        check("vision", "ok", f"Last reading {int(ok_at // 60)} min ago.")

    order = {"down": 2, "warn": 1, "ok": 0}
    level = max((c["level"] for c in checks), key=lambda l: order[l], default="down")
    summary = {
        "down": next((c["text"] for c in checks if c["level"] == "down"), "Offline."),
        "warn": next((c["text"] for c in checks if c["level"] == "warn"), ""),
        "ok": "Watching",
    }[level]
    return {
        "level": level, "summary": summary, "checks": checks,
        "battery": round(batt * 100) if batt is not None else None, "charging": charging,
        "network": d.get("network"), "frames": d.get("frames", 0),
        "resolution": f"{d['width']}×{d['height']}" if d.get("width") else None,
        "version": d.get("version"),
    }


def spoken(h: dict) -> str:
    return "Coop phone: " + " ".join(f"{c['name']}: {c['text']}" for c in h["checks"])
