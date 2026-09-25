# Coop Call

Call your chicken coop. It tells you what happened, what is happening, and what to change. When something goes wrong, it calls you.

Coop Call is the first place built on **Ziso** (Shona for *eye*). An old Android phone watches the coop. A vision model turns what it sees into a timeline. A voice agent answers for the coop on a phone number.

Built for the AssemblyAI Voice Agent Hackathon, September 2026.

## How it works

1. **Sense.** An Android phone in the coop sends frames and sensor readings.
2. **See.** Gemini turns each frame into events: bird count, flock spread, feeder and drinker levels.
3. **Remember.** Events land on a timeline with an hourly baseline of what normal looks like.
4. **Talk.** AssemblyAI's Voice Agent API answers the phone and queries the timeline through tools.
5. **Push.** When a reading drifts from normal, Coop Call messages the owner on WhatsApp, then calls.

## Layout

```
api/     Ziso API: ingest, timeline, tools, alarms
node/    the coop phone: frames and sensors in
web/     dashboard and browser voice
agent/   voice agent configuration and tool schemas
```

## Status

Under construction.

## Setup

Copy `.env.example` to `.env` and fill it in. Full setup instructions arrive with the first build.
