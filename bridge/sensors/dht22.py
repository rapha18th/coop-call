"""Read a DHT22 temperature and humidity sensor on a Raspberry Pi and print JSON for the bridge.

Wiring: data pin to GPIO4 with a 10k pull-up. Install: pip install adafruit-circuitpython-dht
"""

import json
import time

import adafruit_dht
import board

sensor = adafruit_dht.DHT22(board.D4)
for _ in range(5):
    try:
        print(json.dumps({"temperature_c": sensor.temperature, "humidity_pct": sensor.humidity}))
        break
    except RuntimeError:
        time.sleep(2)
sensor.exit()
