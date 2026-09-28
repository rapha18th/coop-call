# Coop Call

Call your chicken coop. It tells you what happened, what is happening, and what to change. When something goes wrong, it calls you.

Coop Call is the first place built on **Ziso** (Shona for *eye*). An old Android phone watches the coop. Gemini turns what it sees into a timeline. An AssemblyAI voice agent answers for the coop, in your browser.

Built for the AssemblyAI Voice Agent Hackathon, September 2026.

## How it works

1. **Sense.** A phone in the coop opens `/node/<coop>` in Chrome. It watches and listens, and decides on the device what is worth sending: a frame when the scene changes or a minute passes, a heartbeat with light, sound and battery every 30 seconds.
2. **See.** Gemini reads each frame into a structured observation: bird count, how the flock is spread, activity, panting, feeder and drinker levels, and anything unusual.
3. **Remember.** Observations land in Firestore and fold into hourly rollups. Each hour is compared with the same hour on earlier days.
4. **Talk.** "Call the coop" opens a live voice session with AssemblyAI's Voice Agent API. The agent answers from the timeline through tools (`coop_now`, `coop_period`, `coop_vs_normal`, `show_picture`, `coop_alarms`, `resolve_alarm`), and every picture it cites appears on screen as evidence.
5. **Push.** Two readings in a row of an empty drinker, a huddled flock or heat stress raise an alarm. Anything unusual, such as a bird down, raises one at once, and two clear pictures in a row close it. The coop rings the owner's phone with a Web Push notification styled as an incoming call. Answering opens the call with the alarm already loaded. It rings again every three minutes until someone answers.

## A harness, not a wrapper

The voice on the call is backed by a working model of the broiler business.

- **The flock.** Age, feed phase, birds alive, and estimated weight against the Cobb500 day-by-day curve, scaled by the farm's own weigh-ins.
- **The feed.** What the birds should eat today in kilos and bags, what was bought, what is on hand, and how many days it lasts. The last two weeks before selling eat about two thirds of a 35-day batch's feed, and the coop says so before the cash is needed.
- **The money.** Spend to date and a projected margin for every sell day from 30 to 49, including what one more day is worth (weight gained minus feed eaten).
- **The routine.** Vaccines due, feed phase switches, weigh days, brooding temperature and lighting for today's age.
- **The records.** Tell the coop "I bought ten bags of finisher for 310 dollars" and it reads the record back, waits for a yes, and books it.
- **The phone.** Battery, charging, network, whether the view is clear or blocked, and whether pictures are being read.

Every call starts with a briefing built from all of the above. Twelve tools let the agent look deeper while it talks.

## Try it without a coop

On any coop you own, open **Camera** and pick a feed. **Connect the video feed** plays broiler-house footage from Pexels. **Connect the red-flag tape** plays a loop in order, one picture a minute: a bird down among the flock for four pictures, then the house clear. The coop calls you when it sees the bird and closes the alarm when the floor is clear again. The loop runs 40 minutes and calls once each time round. Turn on **Let the coop call me** first, or keep the page open and it rings there.

The tape's frames are from "Broilerihalli Isossakyrössä" by Oikeutta eläimille (Animal Rights Finland), CC BY 3.0, via Wikimedia Commons, resized and without sound.

Growth and feed targets: Cobb500 Broiler Performance and Nutrition Supplement (2022). Default prices are Zimbabwe figures from September 2026 and are editable per flock.

## Layout

```
api/       FastAPI on a Hugging Face Space: ingest, vision, timeline, tools, alarms, voice sessions
web/       React on Cloud Run: landing, dashboard and call, the coop phone, the incoming call
bridge/    any RTSP camera (Tapo, Imou, EZVIZ, Hikvision) as a coop camera, with optional sensors
scripts/   deploy the API, generate push keys, create the demo coop
```

## Run it locally

```bash
cp .env.example .env              # add the AssemblyAI and Gemini keys, and a Firebase service account path
python -m venv api/.venv && api/.venv/Scripts/pip install -r api/requirements.txt
python scripts/vapid.py           # push keys for the ring
api/.venv/Scripts/python -m uvicorn app.main:app --app-dir api --port 7860
npm --prefix web install && npm --prefix web run dev
```

Create the public demo coop, with an optional simulated history (flagged as demo data everywhere it appears):

```bash
api/.venv/Scripts/python scripts/demo_coop.py --owner-uid <firebase uid> --simulate-hours 30
```

## Deploy

```bash
api/.venv/Scripts/python scripts/deploy_api.py                                   # Hugging Face Space
gcloud run deploy coop-call --source web --region africa-south1 --allow-unauthenticated   # web
```

## Stack

AssemblyAI Voice Agent API · Gemini 3.5 Flash-Lite · Firebase Auth, Firestore and Storage · FastAPI on Hugging Face Spaces · React on Cloud Run · Web Push
