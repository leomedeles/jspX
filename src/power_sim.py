#!/usr/bin/env python3
import argparse
import json
import os
import random
import signal
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

try:
    import paho.mqtt.client as mqtt  # noqa: F401
    HAVE_MQTT = True
except Exception:
    HAVE_MQTT = False

# # Allow importing sibling modules when running as "python src/power_sim.py"
# HERE = os.path.dirname(__file__)
# if HERE and HERE not in sys.path:
#     sys.path.append(HERE)

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def gen_sample(bus_id: int):
    # Simple, stable-ish pseudo power flow values
    voltage = 1.0 + random.uniform(-0.02, 0.02)  # per-unit ±2%
    p_kw = random.uniform(300.0, 800.0)          # active power kW
    q_kvar = random.uniform(-150.0, 150.0)       # reactive power kvar
    return {
        "ts": now_iso(),
        "bus_id": bus_id,
        "voltage_pu": round(voltage, 3),
        "p_kw": round(p_kw, 1),
        "q_kvar": round(q_kvar, 1),
    }


def ensure_dir(path: str):
    if path:
        os.makedirs(path, exist_ok=True)


def mqtt_defaults():
    """Read container-friendly defaults while preserving CLI overrides."""
    broker_url = os.getenv("BROKER_URL", "mqtt://127.0.0.1:1883")
    parsed = urlparse(broker_url if "://" in broker_url else f"mqtt://{broker_url}")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 1883
    topic = os.getenv("PUB_TOPIC", "telemetry/pandapower")

    try:
        rate_hz = float(os.getenv("RATE_HZ", "1"))
        if rate_hz <= 0:
            raise ValueError
    except ValueError as exc:
        raise SystemExit("RATE_HZ must be a positive number") from exc

    return host, port, topic, 1.0 / rate_hz


def run_file_mode(out_path: str, interval_s: float, producer):
    ensure_dir(os.path.dirname(out_path))
    print(f"[file] appending ndjson to {out_path} every {interval_s}s (Ctrl+C to stop)")
    with open(out_path, "a", encoding="utf-8") as f:
        while True:
            sample = producer()
            line = json.dumps(sample, separators=(",", ":"))
            # Print to stdout and append to file
            print(line, flush=True)
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
            time.sleep(interval_s)


def run_mqtt_mode(host: str, port: int, topic: str, interval_s: float, producer):
    if not HAVE_MQTT:
        print("[mqtt] paho-mqtt not installed. Install with: pip install paho-mqtt", file=sys.stderr)
        sys.exit(2)

    client = mqtt.Client(client_id="", clean_session=True)
    client.connect(host, port, keepalive=60)
    client.loop_start()
    print(f"[mqtt] publishing to {host}:{port} topic '{topic}' every {interval_s}s (Ctrl+C to stop)")

    try:
        while True:
            sample = producer()
            line = json.dumps(sample, separators=(",", ":"))
            print(line, flush=True)
            client.publish(topic, payload=line, qos=0, retain=False)
            time.sleep(interval_s)
    finally:
        client.loop_stop()
        client.disconnect()


def main():
    default_host, default_port, default_topic, default_interval = mqtt_defaults()
    parser = argparse.ArgumentParser(description="jspX SCADA power simulator")
    parser.add_argument("--mqtt", action="store_true", help="Enable MQTT mode (default is file mode)")
    parser.add_argument("--host", default=default_host, help="MQTT broker host")
    parser.add_argument("--port", type=int, default=default_port, help="MQTT broker port")
    parser.add_argument("--topic", default=default_topic, help="MQTT topic to publish to")
    parser.add_argument("--bus-id", type=int, default=1, help="Bus ID in the simulation")
    parser.add_argument("--interval", type=float, default=default_interval, help="Emit interval in seconds")
    parser.add_argument("--out", default=os.path.join("data", "telemetry.ndjson"),
                        help="Output file path for file mode")
    parser.add_argument("--pandapower", action="store_true",
                        help="Use the pandapower 3-bus model (emits {'ts', 'buses':[...]} schema)")
    args = parser.parse_args()

    # Graceful Ctrl+C
    def _sigint(signum, frame):
        print("\n[info] stopping...", file=sys.stderr)
        sys.exit(0)

    signal.signal(signal.SIGINT, _sigint)

    # Choose producer: RNG (legacy) or pandapower grid
    if args.pandapower:
        from power_grid import ThreeBusGrid
        grid = ThreeBusGrid.build()
        producer = grid.step  # returns dict: {"ts":..., "buses":[{...}]}
    else:
        producer = (lambda: gen_sample(args.bus_id))

    if args.mqtt:
        run_mqtt_mode(args.host, args.port, args.topic, args.interval, producer)
    else:
        run_file_mode(args.out, args.interval, producer)


if __name__ == "__main__":
    main()
