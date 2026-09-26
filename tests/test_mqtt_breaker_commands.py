import json
from datetime import datetime

import pytest

from src.breaker_control import BreakerController
from src.power_grid import ReferenceFeederGrid
from src.power_sim import (
    BRK_F1,
    BRK_R1,
    NAMED_COMMAND_TOPICS,
    NAMED_STATUS_TOPICS,
    SCENARIO_COMMAND_TOPIC,
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
        ReferenceFeederGrid.build(seed=1)
    )
    simulator.control_step(timestamp=0.0)
    return simulator, BreakerMqttEventQueue()


def queue_topic(events: BreakerMqttEventQueue, topic: str) -> None:
    events.on_message(None, None, FakeMessage(topic))


def trip_r1(simulator: ControlledPandapowerSimulator) -> None:
    assert simulator.grid.set_scenario(
        ReferenceFeederGrid.TAIL_OVERCURRENT_TEST
    )
    process_control_scan(simulator, timestamp=0.05)
    process_control_scan(simulator, timestamp=0.15)


def test_connect_subscribes_only_to_canonical_contract_and_requests_status() -> None:
    simulator, events = simulator_with_queue()
    client = FakeClient()

    events.on_connect(client, None, None, 0)
    result = process_control_scan(
        simulator, event=events.pop(), timestamp=0.05
    )

    assert client.subscriptions == [
        *((topic, 0) for topic in NAMED_COMMAND_TOPICS.values()),
        (SCENARIO_COMMAND_TOPIC, 0),
    ]
    assert set(result.statuses) == {BRK_F1, BRK_R1}
    assert all(
        status["state"] == "CLOSED"
        for status in result.statuses.values()
    )


def test_named_topics_queue_addressed_commands_and_ignore_other_topics() -> None:
    events = BreakerMqttEventQueue()

    for (breaker_name, command), topic in NAMED_COMMAND_TOPICS.items():
        queue_topic(events, topic)
        event = events.pop()
        assert event is not None
        assert event.breaker_name == breaker_name
        assert event.command == command

    for topic in (
        "cmd/breaker/open",
        "cmd/breaker/close",
        "cmd/breaker/reset",
        "cmd/breaker/BRK_L1_SOURCE/open",
        "cmd/breaker/BRK_L2/open",
        "cmd/breaker/UNKNOWN/open",
        "cmd/breaker/BRK_R1/trip",
    ):
        queue_topic(events, topic)
    assert events.pop() is None


def test_unknown_breaker_is_rejected_by_local_router() -> None:
    simulator, _ = simulator_with_queue()

    with pytest.raises(ValueError, match="unknown breaker: UNKNOWN"):
        simulator.command_breaker("UNKNOWN", "OPEN")


def test_r1_command_is_applied_by_single_writer_control_scan() -> None:
    simulator, events = simulator_with_queue()
    queue_topic(events, NAMED_COMMAND_TOPICS[(BRK_R1, "OPEN")])

    assert simulator.grid.breaker_is_closed(BRK_R1) is True
    result = process_control_scan(
        simulator, event=events.pop(), timestamp=0.05
    )

    assert result.breaker_name == BRK_R1
    assert result.command == "OPEN"
    assert result.command_accepted is True
    assert simulator.controllers[BRK_R1].state == "OPEN"
    assert simulator.grid.breaker_is_closed(BRK_R1) is False
    assert set(result.statuses) == {BRK_R1}
    assert result.statuses[BRK_R1]["breaker"] == BRK_R1


def test_r1_close_is_rejected_while_latched() -> None:
    simulator, events = simulator_with_queue()
    trip_r1(simulator)

    queue_topic(events, NAMED_COMMAND_TOPICS[(BRK_R1, "CLOSE")])
    close_result = process_control_scan(
        simulator, event=events.pop(), timestamp=0.20
    )

    assert close_result.breaker_name == BRK_R1
    assert close_result.command_accepted is False
    assert close_result.statuses[BRK_R1]["state"] == "OPEN"
    assert close_result.statuses[BRK_R1]["tripped"] is True
    assert simulator.grid.breaker_is_closed(BRK_R1) is False


def test_f1_open_and_close_commands_change_physical_switch_on_scan() -> None:
    simulator, events = simulator_with_queue()
    queue_topic(events, NAMED_COMMAND_TOPICS[(BRK_F1, "OPEN")])

    open_result = process_control_scan(
        simulator, event=events.pop(), timestamp=0.05
    )
    assert open_result.command_accepted is True
    assert simulator.controllers[BRK_F1].state == BreakerController.OPEN
    assert simulator.grid.breaker_is_closed(BRK_F1) is False
    assert open_result.statuses[BRK_F1]["state"] == "OPEN"

    queue_topic(events, NAMED_COMMAND_TOPICS[(BRK_F1, "CLOSE")])
    close_result = process_control_scan(
        simulator, event=events.pop(), timestamp=0.10
    )
    assert close_result.command_accepted is True
    assert simulator.controllers[BRK_F1].state == BreakerController.CLOSED
    assert simulator.grid.breaker_is_closed(BRK_F1) is True
    assert close_result.statuses[BRK_F1]["state"] == "CLOSED"


def test_reset_clears_r1_latch_but_requires_later_close() -> None:
    simulator, events = simulator_with_queue()
    trip_r1(simulator)
    assert simulator.grid.set_scenario(ReferenceFeederGrid.NORMAL)
    queue_topic(events, NAMED_COMMAND_TOPICS[(BRK_R1, "RESET")])

    reset_result = process_control_scan(
        simulator, event=events.pop(), timestamp=0.20
    )

    assert reset_result.command_accepted is True
    assert simulator.controllers[BRK_R1].tripped is False
    assert simulator.controllers[BRK_R1].state == BreakerController.OPEN
    assert simulator.grid.breaker_is_closed(BRK_R1) is False
    assert reset_result.statuses[BRK_R1]["trip_reason"] is None

    queue_topic(events, NAMED_COMMAND_TOPICS[(BRK_R1, "CLOSE")])
    close_result = process_control_scan(
        simulator, event=events.pop(), timestamp=0.25
    )
    assert close_result.command_accepted is True
    assert simulator.grid.breaker_is_closed(BRK_R1) is True


def test_named_status_is_identified_strict_json_and_retained() -> None:
    simulator, events = simulator_with_queue()
    client = FakeClient()
    events.on_connect(client, None, None, 0)

    result = process_control_scan(
        simulator, event=events.pop(), timestamp=0.05
    )

    for breaker_name in (BRK_F1, BRK_R1):
        status = result.statuses[breaker_name]
        assert status["breaker"] == breaker_name
        encoded = json.dumps(status, allow_nan=False)
        assert json.loads(encoded) == status
        parsed_ts = datetime.fromisoformat(
            status["ts"].replace("Z", "+00:00")
        )
        assert parsed_ts.utcoffset().total_seconds() == 0
        publish_breaker_status(client, status)

    assert [item[0] for item in client.publications] == [
        NAMED_STATUS_TOPICS[BRK_F1],
        NAMED_STATUS_TOPICS[BRK_R1],
    ]
    for _, payload, qos, retain in client.publications:
        assert json.loads(payload)["breaker"] in (BRK_F1, BRK_R1)
        assert qos == 0
        assert retain is True


def test_publish_rejects_unknown_breaker_status() -> None:
    client = FakeClient()
    status = {
        "ts": "2026-09-23T00:00:00.000Z",
        "breaker": "UNKNOWN",
        "state": "OPEN",
        "tripped": False,
        "undervoltage_alarm": False,
        "trip_reason": None,
    }

    with pytest.raises(ValueError, match="unknown breaker: UNKNOWN"):
        publish_breaker_status(client, status)


def test_r1_protection_trip_returns_immediate_identified_status() -> None:
    simulator, _ = simulator_with_queue()
    assert simulator.grid.set_scenario(
        ReferenceFeederGrid.TAIL_OVERCURRENT_TEST
    )

    pickup = process_control_scan(simulator, timestamp=0.05)
    trip_result = process_control_scan(simulator, timestamp=0.15)

    assert pickup.statuses == {}
    assert set(trip_result.statuses) == {BRK_R1}
    assert trip_result.statuses[BRK_R1]["state"] == "OPEN"
    assert trip_result.statuses[BRK_R1]["tripped"] is True
    assert trip_result.statuses[BRK_R1]["trip_reason"] == "overcurrent"
    assert simulator.grid.breaker_is_closed(BRK_R1) is False


def test_telemetry_has_no_identity_less_breaker_object() -> None:
    simulator, _ = simulator_with_queue()

    telemetry = simulator.control_step(timestamp=0.05)

    assert "breaker" not in telemetry
    json.dumps(telemetry, allow_nan=False)
