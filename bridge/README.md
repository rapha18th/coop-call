# Ziso bridge

Turns any IP camera with an RTSP stream into a coop camera. It runs on a small computer on the same network as the camera, such as a Raspberry Pi Zero 2 W. It looks at the stream every few seconds and sends a picture when something moves or a minute has passed. It sends a heartbeat every 30 seconds, and adds temperature, humidity and ammonia if you give it a sensor. Ziso reads the pictures exactly as it reads a phone's.

## Connect

1. On the coop's page, open **Camera** and tap **Pair a phone or camera**. Copy the pairing link.
2. Find the camera's RTSP address (below), and test it once:

```bash
python ziso_bridge.py --pair "<pairing link>" --camera "<rtsp address>" --once
```

A line like `picture sent: A group of broilers feeding along a trough` means the coop can see.

3. Run it for good as a service:

```bash
sudo mkdir -p /opt/ziso-bridge && sudo cp -r . /opt/ziso-bridge && cd /opt/ziso-bridge
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp ziso-bridge.env.example ziso-bridge.env   # fill in ZISO_PAIR and ZISO_CAMERA
sudo cp ziso-bridge.service /etc/systemd/system/ && sudo systemctl enable --now ziso-bridge
```

## Disconnect

From the coop's Camera sheet, tap **Disconnect**. Or from the bridge:

```bash
python ziso_bridge.py --pair "<pairing link>" --disconnect
```

Either way the old link stops working. Pair again for a new one.

## RTSP addresses

| Camera | Address | Notes |
|---|---|---|
| TP-Link Tapo (C200, C210 and others) | `rtsp://user:pass@<ip>:554/stream1` (`stream2` for lower quality) | Create a camera account in the Tapo app: Device Settings, Advanced Settings, Camera Account. |
| Imou (Ranger 2 and others) | `rtsp://admin:<password>@<ip>:554/cam/realmonitor?channel=1&subtype=0` | `subtype=1` for the lower-quality stream. |
| EZVIZ (C6N and others) | `rtsp://admin:<verification code>@<ip>:554/h264/ch1/main/av_stream` or `.../ch1/main` | Turn RTSP or LAN live view on in the EZVIZ app first. The code is on the camera's label. |
| Hikvision and Hilook | `rtsp://user:pass@<ip>:554/Streaming/Channels/101` | `102` for the sub stream. |

Most 4G solar cameras do not open an RTSP stream, so the bridge cannot read them.

## Sensors

Give the bridge a command that prints one line of JSON with any of `temperature_c`, `humidity_pct` and `ammonia_ppm`:

```bash
ZISO_SENSOR_CMD="python3 /opt/ziso-bridge/sensors/dht22.py"
```

`sensors/dht22.py` reads a DHT22 on a Raspberry Pi. Readings appear in the coop's timeline and the Camera sheet, and the voice can answer "how hot was it at 2 a.m.?"

## Testing without a camera

`--camera` also takes a video file or a webcam number (`0`), so the whole path can be tested on a laptop.
