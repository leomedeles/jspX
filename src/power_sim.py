#!/usr/bin/env python3
import argparse
import json
import os
import random
import signal
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from queue import Empty, SimpleQueue
from typing import Callable
from urllib.parse import urlparse

if __package__:
    from .breaker_control import BreakerController
    from .ied import REFERENCE_IED_CONFIGS, SimulatedIED
else:
    from breaker_control import BreakerController
    from ied import REFERENCE_IED_CONFIGS, SimulatedIED

try:
    import paho.mqtt.client as mqtt  # noqa: F401
    HAVE_MQTT = True
except Exception:
    HAVE_MQTT = False


CONTROL_INTERVAL_S = 0.050
SCENARIO_COMMAND_TOPIC = "cmd/sim/scenario/set"
IED_EVENT_TOPIC = "event/ied"
BRK_F1 = "BRK_F1"
BRK_R1 = "BRK_R1"
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
    topic: breaker_and_command
    for breaker_and_command, topic in NAMED_COMMAND_TOPICS.items()
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
    command: str | None
    command_accepted: bool | None
    scenario: str | None = None
    scenario_accepted: bool | None = None
    breaker_name: str | None = None
    statuses: dict[str, dict[str, object]] = field(default_factory=dict)
    events: tuple[dict[str, object], ...] = ()


class ControlledPandapowerSimulator:
    """Coordinate authoritative breaker controllers with the physical grid."""

    def __init__(
        self,
        grid,
        f1_controller: BreakerController | None = None,
        *,
        r1_controller: BreakerController | None = None,
    ) -> None:
        self.grid = grid
        provided = {BRK_F1: f1_controller, BRK_R1: r1_controller}
        self.ieds = {
            config.breaker: SimulatedIED(config, provided[config.breaker])
            for config in REFERENCE_IED_CONFIGS
        }
        self.controllers = {
            name: ied.controller for name, ied in self.ieds.items()
        }
        self._pending_operations: dict[str, tuple[bool, str]] = {}
        self._pending_events: list[tuple[str, str, dict[str, object]]] = []
        self.last_events: tuple[dict[str, object], ...] = ()
        self._event_run_id = uuid.uuid4().hex
        self._event_sequence = 0

    def _record_event(self, breaker_name: str, event: str, **fields: object) -> None:
        self._pending_events.append((breaker_name, event, fields))

    def command_breaker(self, breaker_name: str, command: str) -> bool:
        """Apply a local command to one controller, not the physical switch."""
        try:
            controller = self.controllers[breaker_name]
        except KeyError as exc:
            raise ValueError(f"unknown breaker: {breaker_name}") from exc
        timing_started = controller.timing_started_at is not None
        accepted = apply_breaker_command(controller, command)
        if accepted and command in ("OPEN", "CLOSE"):
            self._record_event(
                breaker_name, "OPERATION_REQUEST",
                requested_state="CLOSED" if command == "CLOSE" else "OPEN",
                cause="operator",
            )
            self._pending_operations[breaker_name] = (command == "CLOSE", "operator")
            if command == "OPEN" and timing_started:
                self._record_event(breaker_name, "TIMING_CANCELLED")
        elif command == "RESET":
            self._record_event(breaker_name, "RESET")
        elif command == "CLOSE" and not accepted:
            self._record_event(breaker_name, "CLOSE_REJECTED", cause="trip_latch")
        return accepted

    def _apply_pending_operations(self) -> None:
        """Attempt each accepted request once at the plant-operation boundary."""
        operations = self._pending_operations
        self._pending_operations = {}
        for breaker_name, (closed, cause) in operations.items():
            self.grid.set_breaker_closed(breaker_name, closed)
            actual_closed = self.grid.breaker_is_closed(breaker_name)
            self._record_event(
                breaker_name, "POSITION_FEEDBACK",
                requested_state="CLOSED" if closed else "OPEN",
                actual_state="CLOSED" if actual_closed else "OPEN",
                success=actual_closed == closed,
                cause=cause,
            )

    def _evaluate_protection(self, timestamp: float) -> None:
        """Evaluate both breakers from solved plant measurements."""
        for ied in self.ieds.values():
            ied.evaluate(self.grid, timestamp)
            for transition in ied.controller.transitions:
                self._record_event(ied.config.breaker, transition)
                if transition == "TRIP_REQUEST":
                    self._pending_operations[ied.config.breaker] = (False, "protection")

    def _finish_events(self, timestamp: float) -> None:
        scan_ts = now_iso()
        events = []
        for breaker_name, event, fields in self._pending_events:
            self._event_sequence += 1
            controller = self.controllers[breaker_name]
            events.append({
                "ts": scan_ts,
                "event_id": f"{self._event_run_id}:{self._event_sequence}",
                "ied": self.ieds[breaker_name].config.event_source,
                "breaker": breaker_name,
                "event": event,
                "scan_monotonic_s": float(timestamp),
                "position": (
                    "CLOSED" if self.grid.breaker_is_closed(breaker_name) else "OPEN"
                ),
                "tripped": controller.tripped,
                **fields,
            })
        self.last_events = tuple(events)
        self._pending_events.clear()

    def control_step(
        self, *, timestamp: float | None = None, vary_load: bool = False
    ) -> dict[str, object]:
        """Run one solve/protection scan and return the resulting topology."""
        now = time.monotonic() if timestamp is None else timestamp

        self._apply_pending_operations()
        telemetry = self.grid.solve(vary_load=vary_load)
        self._evaluate_protection(now)
        if self._pending_operations:
            self._apply_pending_operations()
            telemetry = self.grid.solve()

        self._finish_events(now)
        return telemetry


def breaker_status_payload(
    controller, breaker_name: str, physical_closed: bool
) -> dict[str, object]:
    """Build retained status from post-scan position and IED state."""
    snapshot = controller.snapshot()
    snapshot["state"] = "CLOSED" if physical_closed else "OPEN"
    return {
        "ts": now_iso(),
        "breaker": breaker_name,
        **snapshot,
    }


def publish_breaker_status(
    client,
    status: dict[str, object],
):
    """Publish one authoritative, retained, strict-JSON status snapshot."""
    payload = json.dumps(status, separators=(",", ":"), allow_nan=False)
    breaker_name = str(status["breaker"])
    try:
        topic = NAMED_STATUS_TOPICS[breaker_name]
    except KeyError as exc:
        raise ValueError(f"unknown breaker: {breaker_name}") from exc
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
        name: (controller.snapshot(), simulator.grid.breaker_is_closed(name))
        for name, controller in simulator.controllers.items()
    }
    command = event.command if event is not None else None
    breaker_name = (
        event.breaker_name
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
        name: (controller.snapshot(), simulator.grid.breaker_is_closed(name))
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
            simulator.controllers[name], name, simulator.grid.breaker_is_closed(name)
        )
        for name in simulator.controllers
        if name in status_due
    }

    return ControlScanResult(
        telemetry=telemetry,
        command=command,
        command_accepted=accepted,
        scenario=scenario,
        scenario_accepted=scenario_accepted,
        breaker_name=breaker_name,
        statuses=statuses,
        events=simulator.last_events,
    )


def publish_ied_event(client, event: dict[str, object]):
    """Publish one identified scan event without MQTT retention."""
    return client.publish(
        IED_EVENT_TOPIC,
        payload=json.dumps(event, separators=(",", ":"), allow_nan=False),
        qos=0,
        retain=False,
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

                for status in result.statuses.values():
                    publish_breaker_status(client, status)
                for ied_event in result.events:
                    publish_ied_event(client, ied_event)

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
