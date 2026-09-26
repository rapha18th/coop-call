"""Gemini reads a coop frame and returns what a keeper would notice."""

from __future__ import annotations

import json
import logging
from functools import lru_cache

from google import genai
from google.genai import types

from . import config

log = logging.getLogger("coop.vision")

LEVELS = ["full", "half", "low", "empty", "not_visible"]

SCHEMA = {
    "type": "object",
    "properties": {
        "birds": {"type": "integer", "description": "Birds visible in the frame. 0 if none."},
        "spread": {
            "type": "string",
            "enum": ["even", "huddled", "crowded_feeder", "crowded_drinker",
                     "avoiding_area", "clustered_edges", "empty", "unclear"],
            "description": (
                "How the flock is distributed. huddled: packed tightly together, "
                "often under or near heat, a cold sign. clustered_edges or "
                "avoiding_area: birds keeping away from one spot, often too hot or "
                "a draught. even: spread across the floor, comfortable."
            ),
        },
        "activity": {"type": "string", "enum": ["resting", "calm", "active", "agitated", "unclear"]},
        "panting": {"type": "boolean", "description": "Beaks open or wings held away from the body, a heat sign."},
        "feeder": {"type": "string", "enum": LEVELS},
        "drinker": {"type": "string", "enum": LEVELS},
        "lights": {"type": "string", "enum": ["on", "off", "daylight", "unclear"]},
        "unusual": {
            "type": "string",
            "description": (
                "One short sentence about anything a keeper must know now: a bird "
                "lying still apart from the flock, a predator, a person, water on the "
                "floor, smoke, a broken fence. Empty string if nothing."
            ),
        },
        "summary": {"type": "string", "description": "One plain sentence describing the scene."},
    },
    "required": ["birds", "spread", "activity", "panting", "feeder", "drinker", "lights",
                 "unusual", "summary"],
}

PROMPT = (
    "You are watching a small poultry house through a fixed phone camera. Describe "
    "only what is visible. Count birds carefully; estimate when many overlap. Judge "
    "feeder and drinker levels only if you can see them, otherwise say not_visible. "
    "Never guess at disease."
)


@lru_cache
def client() -> genai.Client:
    return genai.Client(api_key=config.GEMINI_API_KEY)


def read_frame(jpeg: bytes) -> dict:
    response = client().models.generate_content(
        model=config.VISION_MODEL,
        contents=[types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"), PROMPT],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=SCHEMA,
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
            temperature=0.1,
        ),
    )
    data = json.loads(response.text)
    data["unusual"] = (data.get("unusual") or "").strip()
    return data
