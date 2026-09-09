#!/usr/bin/env python3
import argparse
import json
import os
import random
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlparse

try:
    import paho.mqtt.client as mqtt  # noqa: F401
    HAVE_MQTT = True
except Exception:
    HAVE_MQTT = False


CONTROL_INTERVAL_S = 0.050


class ControlledPandapowerSimulator:
    """Coordinate one controller with one physical pandapower grid."""

    def __init__(self, grid, controller) -> None:
        self.grid = grid
        self.controller = controller

    def control_step(
        self, *, timestamp: float | None = None, vary_load: bool = False
    ) -> dict[str, object]:
        """Run one solve/protection scan and return the resulting topology."""
        now = time.monotonic() if timestamp is None else timestamp

        self.grid.set_breaker_closed(
            self.controller.state == self.controller.CLOSED
        )
        telemetry = self.grid.solve(vary_load=vary_load)

        applied_state = self.controller.state
        self.controller.evaluate(
            current_percent=self.grid.protected_line_loading_percent(),
            voltages_pu=self.grid.downstream_voltages_pu(),
            timestamp=now,
        )

        if self.controller.state != applied_state:
            self.grid.set_breaker_closed(
                self.controller.state == self.controller.CLOSED
            )
            telemetry = self.grid.solve()

        telemetry["breaker"] = self.controller.snapshot()
        return telemetry

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
            line = json.dumps(sample, separators=(",", ":"), allow_nan=False)
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
            line = json.dumps(sample, separators=(",", ":"), allow_nan=False)
            print(line, flush=True)
            client.publish(topic, payload=line, qos=0, retain=False)
            time.sleep(interval_s)
    finally:
        client.loop_stop()
        client.disconnect()


def run_controlled_loop(
    simulator: ControlledPandapowerSimulator,
    *,
    publish_interval_s: float,
    publish: Callable[[dict[str, object]], None],
    control_interval_s: float = CONTROL_INTERVAL_S,
) -> None:
    """Run protection scans independently of the slower telemetry cadence."""
    next_control = time.monotonic()
    next_publish = next_control

    while True:
        now = time.monotonic()
        if now >= next_control:
            publish_due = now >= next_publish
            sample = simulator.control_step(
                timestamp=now,
                vary_load=publish_due,
            )
            next_control += control_interval_s
            if next_control <= now:
                next_control = now + control_interval_s

            if publish_due:
                publish(sample)
                next_publish += publish_interval_s
                if next_publish <= now:
                    next_publish = now + publish_interval_s

        # Publication is sampled from a completed control scan, so the next
        # useful wake-up is always the next control deadline.
        time.sleep(max(0.0, next_control - time.monotonic()))


def run_controlled_file_mode(
    out_path: str,
    interval_s: float,
    simulator: ControlledPandapowerSimulator,
) -> None:
    ensure_dir(os.path.dirname(out_path))
    print(
        f"[file] appending ndjson to {out_path} every {interval_s}s "
        f"with {CONTROL_INTERVAL_S}s control scans (Ctrl+C to stop)"
    )
    with open(out_path, "a", encoding="utf-8") as output:
        def publish(sample: dict[str, object]) -> None:
            line = json.dumps(sample, separators=(",", ":"), allow_nan=False)
            print(line, flush=True)
            output.write(line + "\n")
            output.flush()
            os.fsync(output.fileno())

        run_controlled_loop(
            simulator,
            publish_interval_s=interval_s,
            publish=publish,
        )


def run_controlled_mqtt_mode(
    host: str,
    port: int,
    topic: str,
    interval_s: float,
    simulator: ControlledPandapowerSimulator,
) -> None:
    if not HAVE_MQTT:
        print(
            "[mqtt] paho-mqtt not installed. Install with: pip install paho-mqtt",
            file=sys.stderr,
        )
        sys.exit(2)

    client = mqtt.Client(client_id="", clean_session=True)
    client.connect(host, port, keepalive=60)
    client.loop_start()
    print(
        f"[mqtt] publishing to {host}:{port} topic '{topic}' every {interval_s}s "
        f"with {CONTROL_INTERVAL_S}s control scans (Ctrl+C to stop)"
    )

    try:
        def publish(sample: dict[str, object]) -> None:
            line = json.dumps(sample, separators=(",", ":"), allow_nan=False)
            print(line, flush=True)
            client.publish(topic, payload=line, qos=0, retain=False)

        run_controlled_loop(
            simulator,
            publish_interval_s=interval_s,
            publish=publish,
        )
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
        from breaker_control import BreakerController
        from power_grid import ThreeBusGrid

        simulator = ControlledPandapowerSimulator(
            ThreeBusGrid.build(), BreakerController()
        )
        if args.mqtt:
            run_controlled_mqtt_mode(
                args.host, args.port, args.topic, args.interval, simulator
            )
        else:
            run_controlled_file_mode(args.out, args.interval, simulator)
        return
    else:
        producer = (lambda: gen_sample(args.bus_id))

    if args.mqtt:
        run_mqtt_mode(args.host, args.port, args.topic, args.interval, producer)
    else:
        run_file_mode(args.out, args.interval, producer)


if __name__ == "__main__":
    main()
