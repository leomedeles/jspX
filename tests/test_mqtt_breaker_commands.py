import json
from datetime import datetime

from src.breaker_control import BreakerController
from src.power_grid import ThreeBusGrid
from src.power_sim import (
    BREAKER_STATUS_TOPIC,
    CLOSE_COMMAND_TOPIC,
    OPEN_COMMAND_TOPIC,
    RESET_COMMAND_TOPIC,
    BreakerMqttEventQueue,
    ControlledPandapowerSimulator,
    process_control_scan,
    publish_breaker_status,
)


class FakeMessage:
    def __init__(self, topic: str, payload: bytes = b"ignored") -> None:
        self.topic = topic
        self.payload = payload


class FakeClient:
    def __init__(self) -> None:
        self.subscriptions: list[tuple[str, int]] = []
        self.publications: list[tuple[str, str, int, bool]] = []

    def subscribe(self, topic: str, qos: int) -> None:
        self.subscriptions.append((topic, qos))

    def publish(self, topic: str, payload: str, qos: int, retain: bool) -> None:
        self.publications.append((topic, payload, qos, retain))


def simulator_with_queue() -> tuple[
    ControlledPandapowerSimulator, BreakerMqttEventQueue
]:
    simulator = ControlledPandapowerSimulator(
        ThreeBusGrid.build(seed=1), BreakerController()
    )
    simulator.control_step(timestamp=0.0)
    return simulator, BreakerMqttEventQueue()


def queue_topic(events: BreakerMqttEventQueue, topic: str) -> None:
    events.on_message(None, None, FakeMessage(topic))


def test_connect_subscribes_to_contract_and_requests_initial_status() -> None:
    simulator, events = simulator_with_queue()
    client = FakeClient()

    events.on_connect(client, None, None, 0)
    result = process_control_scan(
        simulator, event=events.pop(), timestamp=0.05
    )

    assert client.subscriptions == [
        (OPEN_COMMAND_TOPIC, 0),
        (CLOSE_COMMAND_TOPIC, 0),
        (RESET_COMMAND_TOPIC, 0),
    ]
    assert BREAKER_STATUS_TOPIC == "status/breaker"
    assert result.status is not None
    assert result.status["state"] == "CLOSED"


def test_open_command_waits_for_scan_then_opens_physical_switch() -> None:
    simulator, events = simulator_with_queue()
    queue_topic(events, OPEN_COMMAND_TOPIC)

    assert simulator.grid.breaker_closed is True
    result = process_control_scan(
        simulator, event=events.pop(), timestamp=0.05
    )

    assert result.command == "OPEN"
    assert result.command_accepted is True
    assert simulator.controller.state == "OPEN"
    assert simulator.grid.breaker_closed is False
    assert result.status["state"] == "OPEN"


def test_close_command_reenergizes_switch_when_not_tripped() -> None:
    simulator, events = simulator_with_queue()
    queue_topic(events, OPEN_COMMAND_TOPIC)
    process_control_scan(simulator, event=events.pop(), timestamp=0.05)
    queue_topic(events, CLOSE_COMMAND_TOPIC)

    result = process_control_scan(
        simulator, event=events.pop(), timestamp=0.10
    )

    assert result.command_accepted is True
    assert simulator.controller.state == "CLOSED"
    assert simulator.grid.breaker_closed is True
    assert result.status["state"] == "CLOSED"


def trip(simulator: ControlledPandapowerSimulator) -> None:
    simulator.grid.net.line.at[simulator.grid.protected_line_idx, "max_i_ka"] = 0.02
    process_control_scan(simulator, timestamp=0.05)
    process_control_scan(simulator, timestamp=0.15)


def test_close_is_rejected_while_tripped_and_switch_stays_open() -> None:
    simulator, events = simulator_with_queue()
    trip(simulator)
    queue_topic(events, CLOSE_COMMAND_TOPIC)

    result = process_control_scan(
        simulator, event=events.pop(), timestamp=0.20
    )

    assert result.command_accepted is False
    assert simulator.controller.tripped is True
    assert simulator.controller.state == "OPEN"
    assert simulator.grid.breaker_closed is False
    assert result.status["tripped"] is True


def test_reset_clears_latch_but_requires_later_close() -> None:
    simulator, events = simulator_with_queue()
    trip(simulator)
    queue_topic(events, RESET_COMMAND_TOPIC)

    reset_result = process_control_scan(
        simulator, event=events.pop(), timestamp=0.20
    )

    assert reset_result.command_accepted is True
    assert simulator.controller.tripped is False
    assert simulator.controller.state == "OPEN"
    assert simulator.grid.breaker_closed is False
    assert reset_result.status["trip_reason"] is None

    queue_topic(events, CLOSE_COMMAND_TOPIC)
    close_result = process_control_scan(
        simulator, event=events.pop(), timestamp=0.25
    )
    assert close_result.command_accepted is True
    assert simulator.grid.breaker_closed is True


def test_status_is_strict_json_and_exactly_matches_controller_snapshot() -> None:
    simulator, events = simulator_with_queue()
    queue_topic(events, OPEN_COMMAND_TOPIC)

    result = process_control_scan(
        simulator, event=events.pop(), timestamp=0.05
    )

    assert result.status is not None
    encoded = json.dumps(result.status, allow_nan=False)
    assert json.loads(encoded) == result.status
    assert {key: value for key, value in result.status.items() if key != "ts"} == (
        simulator.controller.snapshot()
    )
    parsed_ts = datetime.fromisoformat(result.status["ts"].replace("Z", "+00:00"))
    assert parsed_ts.utcoffset().total_seconds() == 0

    client = FakeClient()
    publish_breaker_status(client, result.status)
    topic, payload, qos, retain = client.publications[0]
    assert topic == BREAKER_STATUS_TOPIC
    assert json.loads(payload) == result.status
    assert qos == 0
    assert retain is True


def test_protection_trip_returns_open_switch_status() -> None:
    simulator, _ = simulator_with_queue()
    simulator.grid.net.line.at[simulator.grid.protected_line_idx, "max_i_ka"] = 0.02

    pickup = process_control_scan(simulator, timestamp=0.05)
    trip_result = process_control_scan(simulator, timestamp=0.15)

    assert pickup.status is None
    assert trip_result.status is not None
    assert trip_result.status["state"] == "OPEN"
    assert trip_result.status["tripped"] is True
    assert trip_result.status["trip_reason"] == "overcurrent"
    assert simulator.grid.breaker_closed is False
