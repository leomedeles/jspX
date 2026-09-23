#!/usr/bin/env python3
import argparse
import json
import os
import random
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from queue import Empty, SimpleQueue
from typing import Callable
from urllib.parse import urlparse

if __package__:
    from .breaker_control import BreakerController
else:
    from breaker_control import BreakerController

try:
    import paho.mqtt.client as mqtt  # noqa: F401
    HAVE_MQTT = True
except Exception:
    HAVE_MQTT = False


CONTROL_INTERVAL_S = 0.050
OPEN_COMMAND_TOPIC = "cmd/breaker/open"
CLOSE_COMMAND_TOPIC = "cmd/breaker/close"
RESET_COMMAND_TOPIC = "cmd/breaker/reset"
BREAKER_STATUS_TOPIC = "status/breaker"
SCENARIO_COMMAND_TOPIC = "cmd/sim/scenario/set"
BRK_F1 = "BRK_F1"
BRK_R1 = "BRK_R1"
OVERCURRENT_PICKUP_KA = 0.20
F1_TRIP_DELAY_S = 0.300
R1_TRIP_DELAY_S = 0.100

NAMED_COMMAND_TOPICS = {
    (breaker_name, command): (
        f"cmd/breaker/{breaker_name}/{command.lower()}"
    )
    for breaker_name in (BRK_F1, BRK_R1)
    for command in ("OPEN", "CLOSE", "RESET")
}
NAMED_STATUS_TOPICS = {
    breaker_name: f"status/breaker/{breaker_name}"
    for breaker_name in (BRK_F1, BRK_R1)
}
COMMAND_BY_TOPIC = {
    OPEN_COMMAND_TOPIC: (BRK_F1, "OPEN"),
    CLOSE_COMMAND_TOPIC: (BRK_F1, "CLOSE"),
    RESET_COMMAND_TOPIC: (BRK_F1, "RESET"),
    **{
        topic: breaker_and_command
        for breaker_and_command, topic in NAMED_COMMAND_TOPICS.items()
    },
}


@dataclass(frozen=True)
class BreakerMqttEvent:
    """One callback-produced event for the single-writer control loop."""

    command: str | None = None
    breaker_name: str | None = None
    status_requested: bool = False
    scenario: str | None = None


class BreakerMqttEventQueue:
    """Translate MQTT callbacks into thread-safe, side-effect-free events."""

    def __init__(self) -> None:
        self._events: SimpleQueue[BreakerMqttEvent] = SimpleQueue()

    def on_connect(self, client, userdata, flags, rc) -> None:
        """Subscribe on successful connection and request startup status."""
        if rc != 0:
            return
        for topic in COMMAND_BY_TOPIC:
            client.subscribe(topic, qos=0)
        client.subscribe(SCENARIO_COMMAND_TOPIC, qos=0)
        self._events.put(BreakerMqttEvent(status_requested=True))

    def on_message(self, client, userdata, message) -> None:
        """Translate an MQTT message into queued control-loop intent."""
        breaker_command = COMMAND_BY_TOPIC.get(message.topic)
        if breaker_command is not None:
            breaker_name, command = breaker_command
            self._events.put(
                BreakerMqttEvent(
                    command=command,
                    breaker_name=breaker_name,
                )
            )
        elif message.topic == SCENARIO_COMMAND_TOPIC:
            try:
                scenario = bytes(message.payload).decode("utf-8")
            except UnicodeDecodeError:
                scenario = ""
            self._events.put(BreakerMqttEvent(scenario=scenario))

    def pop(self) -> BreakerMqttEvent | None:
        """Return the next event without blocking the control loop."""
        try:
            return self._events.get_nowait()
        except Empty:
            return None


@dataclass(frozen=True)
class ControlScanResult:
    telemetry: dict[str, object]
    status: dict[str, object] | None
    command: str | None
    command_accepted: bool | None
    scenario: str | None = None
    scenario_accepted: bool | None = None
    breaker_name: str | None = None
    statuses: dict[str, dict[str, object]] = field(default_factory=dict)


class ControlledPandapowerSimulator:
    """Coordinate authoritative breaker controllers with the physical grid."""

    def __init__(
        self,
        grid,
        controller: BreakerController | None = None,
        *,
        r1_controller: BreakerController | None = None,
    ) -> None:
        self.grid = grid
        self.controllers = {
            BRK_F1: (
                controller
                if controller is not None
                else BreakerController(
                    pickup_ka=OVERCURRENT_PICKUP_KA,
                    trip_delay_s=F1_TRIP_DELAY_S,
                )
            ),
            BRK_R1: (
                r1_controller
                if r1_controller is not None
                else BreakerController(
                    pickup_ka=OVERCURRENT_PICKUP_KA,
                    trip_delay_s=R1_TRIP_DELAY_S,
                )
            ),
        }
        self.controller = self.controllers[BRK_F1]

    def command_breaker(self, breaker_name: str, command: str) -> bool:
        """Apply a local command to one controller, not the physical switch."""
        try:
            controller = self.controllers[breaker_name]
        except KeyError as exc:
            raise ValueError(f"unknown breaker: {breaker_name}") from exc
        return apply_breaker_command(controller, command)

    def _apply_controller_states(self) -> None:
        """Write both authoritative controller positions to the plant model."""
        for breaker_name, controller in self.controllers.items():
            self.grid.set_breaker_closed(
                breaker_name, controller.state == controller.CLOSED
            )

    def _evaluate_protection(self, timestamp: float) -> None:
        """Evaluate both breakers from solved plant measurements."""
        self.controllers[BRK_R1].evaluate(
            current_ka=self.grid.breaker_current_ka(BRK_R1),
            voltages_pu=(),
            timestamp=timestamp,
        )
        self.controllers[BRK_F1].evaluate(
            current_ka=self.grid.breaker_current_ka(BRK_F1),
            voltages_pu=(
                self.grid.bus_voltage_pu(self.grid.BUS_MV_SOURCE),
            ),
            timestamp=timestamp,
        )

    def control_step(
        self, *, timestamp: float | None = None, vary_load: bool = False
    ) -> dict[str, object]:
        """Run one solve/protection scan and return the resulting topology."""
        now = time.monotonic() if timestamp is None else timestamp

        self._apply_controller_states()
        telemetry = self.grid.solve(vary_load=vary_load)

        applied_states = {
            name: controller.state
            for name, controller in self.controllers.items()
        }
        self._evaluate_protection(now)

        if any(
            controller.state != applied_states[name]
            for name, controller in self.controllers.items()
        ):
            self._apply_controller_states()
            telemetry = self.grid.solve()

        telemetry["breaker"] = self.controller.snapshot()
        return telemetry


def breaker_status_payload(
    controller, breaker_name: str | None = None
) -> dict[str, object]:
    """Build authoritative status from the controller's current snapshot."""
    identity = {"breaker": breaker_name} if breaker_name is not None else {}
    return {"ts": now_iso(), **identity, **controller.snapshot()}


def publish_breaker_status(
    client,
    status: dict[str, object],
    *,
    breaker_name: str | None = None,
):
    """Publish one authoritative, retained, strict-JSON status snapshot."""
    payload = json.dumps(status, separators=(",", ":"), allow_nan=False)
    topic = (
        BREAKER_STATUS_TOPIC
        if breaker_name is None
        else NAMED_STATUS_TOPICS[breaker_name]
    )
    return client.publish(
        topic,
        payload=payload,
        qos=0,
        retain=True,
    )


def apply_breaker_command(controller, command: str) -> bool:
    """Route a command exclusively through the BreakerController API."""
    if command == "OPEN":
        controller.open()
        return True
    if command == "CLOSE":
        return controller.close()
    if command == "RESET":
        controller.reset()
        return True
    raise ValueError(f"unsupported breaker command: {command}")


def process_control_scan(
    simulator: ControlledPandapowerSimulator,
    *,
    event: BreakerMqttEvent | None = None,
    timestamp: float | None = None,
    vary_load: bool = False,
) -> ControlScanResult:
    """Apply at most one queued command, solve the plant, and derive status."""
    before = {
        name: controller.snapshot()
        for name, controller in simulator.controllers.items()
    }
    command = event.command if event is not None else None
    breaker_name = (
        event.breaker_name or BRK_F1
        if event is not None and command is not None
        else None
    )
    scenario = event.scenario if event is not None else None
    accepted = (
        simulator.command_breaker(breaker_name, command)
        if command is not None
        else None
    )
    scenario_accepted = (
        simulator.grid.set_scenario(scenario)
        if scenario is not None
        else None
    )

    telemetry = simulator.control_step(timestamp=timestamp, vary_load=vary_load)
    after = {
        name: controller.snapshot()
        for name, controller in simulator.controllers.items()
    }
    status_requested = event.status_requested if event is not None else False
    status_due = {
        name
        for name in simulator.controllers
        if status_requested
        or name == breaker_name
        or after[name] != before[name]
    }
    statuses = {
        name: breaker_status_payload(
            simulator.controllers[name], breaker_name=name
        )
        for name in simulator.controllers
        if name in status_due
    }
    legacy_status = (
        breaker_status_payload(simulator.controller)
        if BRK_F1 in status_due
        else None
    )

    return ControlScanResult(
        telemetry=telemetry,
        status=legacy_status,
        command=command,
        command_accepted=accepted,
        scenario=scenario,
        scenario_accepted=scenario_accepted,
        breaker_name=breaker_name,
        statuses=statuses,
    )

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

    event_queue = BreakerMqttEventQueue()
    client = mqtt.Client(client_id="", clean_session=True)
    client.on_connect = event_queue.on_connect
    client.on_message = event_queue.on_message
    client.connect(host, port, keepalive=60)
    client.loop_start()
    print(
        f"[mqtt] publishing to {host}:{port} topic '{topic}' every {interval_s}s "
        f"with {CONTROL_INTERVAL_S}s control scans (Ctrl+C to stop)"
    )

    next_control = time.monotonic()
    next_publish = next_control

    try:
        while True:
            now = time.monotonic()
            if now >= next_control:
                publish_due = now >= next_publish
                result = process_control_scan(
                    simulator,
                    event=event_queue.pop(),
                    timestamp=now,
                    vary_load=publish_due,
                )

                if result.status is not None:
                    publish_breaker_status(client, result.status)
                for breaker_name, status in result.statuses.items():
                    publish_breaker_status(
                        client,
                        status,
                        breaker_name=breaker_name,
                    )

                if publish_due:
                    line = json.dumps(
                        result.telemetry,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                    print(line, flush=True)
                    client.publish(topic, payload=line, qos=0, retain=False)
                    next_publish += interval_s
                    if next_publish <= now:
                        next_publish = now + interval_s

                next_control += CONTROL_INTERVAL_S
                if next_control <= now:
                    next_control = now + CONTROL_INTERVAL_S

            time.sleep(max(0.0, next_control - time.monotonic()))
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
                        help="Use the pandapower reference feeder model")
    args = parser.parse_args()

    # Graceful Ctrl+C
    def _sigint(signum, frame):
        print("\n[info] stopping...", file=sys.stderr)
        sys.exit(0)

    signal.signal(signal.SIGINT, _sigint)

    # Choose producer: RNG (legacy) or pandapower grid
    if args.pandapower:
        from power_grid import ReferenceFeederGrid

        simulator = ControlledPandapowerSimulator(
            ReferenceFeederGrid.build()
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
