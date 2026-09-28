"""Scan event order, physical feedback, and non-retained publication."""

import json

from src.power_grid import ReferenceFeederGrid
from src.power_sim import (
    BRK_F1,
    BRK_R1,
    IED_EVENT_TOPIC,
    BreakerMqttEvent,
    ControlledPandapowerSimulator,
    process_control_scan,
    publish_ied_event,
)


class FakeClient:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, qos, retain):
        self.published.append((topic, payload, qos, retain))


def events_for(result, breaker):
    return [event for event in result.events if event["breaker"] == breaker]


def test_successful_primary_trace_cancels_f1_timing_after_current_clears() -> None:
    grid = ReferenceFeederGrid.build(seed=1)
    simulator = ControlledPandapowerSimulator(grid)
    pickup = process_control_scan(
        simulator,
        event=BreakerMqttEvent(scenario=grid.TAIL_OVERCURRENT_TEST),
        timestamp=0.0,
    )
    assert [e["event"] for e in events_for(pickup, BRK_R1)] == [
        "PICKUP", "TIMING_STARTED"
    ]
    assert [e["event"] for e in events_for(pickup, BRK_F1)] == [
        "PICKUP", "TIMING_STARTED"
    ]

    process_control_scan(simulator, timestamp=0.05)
    trip = process_control_scan(simulator, timestamp=0.10)
    assert [e["event"] for e in events_for(trip, BRK_R1)] == [
        "TRIP_REQUEST", "POSITION_FEEDBACK"
    ]
    feedback = events_for(trip, BRK_R1)[-1]
    assert feedback["requested_state"] == "OPEN"
    assert feedback["actual_state"] == "OPEN"
    assert feedback["success"] is True
    assert grid.breaker_is_closed(BRK_R1) is False

    cancelled = process_control_scan(simulator, timestamp=0.15)
    assert [e["event"] for e in events_for(cancelled, BRK_F1)] == [
        "TIMING_CANCELLED"
    ]
    assert grid.breaker_is_closed(BRK_F1) is True
    assert process_control_scan(simulator, timestamp=0.30).events == ()


def test_failed_primary_trace_backup_and_interlock_events_are_truthful() -> None:
    grid = ReferenceFeederGrid.build(seed=1)
    simulator = ControlledPandapowerSimulator(grid)
    process_control_scan(
        simulator,
        event=BreakerMqttEvent(scenario=grid.R1_OPENING_FAILURE_TEST),
        timestamp=0.0,
    )
    process_control_scan(simulator, timestamp=0.05)
    primary = process_control_scan(simulator, timestamp=0.10)
    failed = events_for(primary, BRK_R1)[-1]
    assert failed["event"] == "POSITION_FEEDBACK"
    assert failed["requested_state"] == "OPEN"
    assert failed["actual_state"] == failed["position"] == "CLOSED"
    assert failed["success"] is False
    assert failed["tripped"] is True
    assert primary.statuses[BRK_R1]["state"] == "CLOSED"

    rejected = process_control_scan(
        simulator,
        event=BreakerMqttEvent(command="CLOSE", breaker_name=BRK_R1),
        timestamp=0.15,
    )
    assert rejected.command_accepted is False
    assert [e["event"] for e in rejected.events] == ["CLOSE_REJECTED"]
    assert rejected.events[0]["position"] == "CLOSED"
    for t in (0.20, 0.25):
        process_control_scan(simulator, timestamp=t)
    backup = process_control_scan(simulator, timestamp=0.30)
    assert [e["event"] for e in events_for(backup, BRK_F1)] == [
        "TRIP_REQUEST", "POSITION_FEEDBACK"
    ]
    assert events_for(backup, BRK_F1)[-1]["success"] is True
    assert events_for(backup, BRK_F1)[-1]["actual_state"] == "OPEN"
    assert grid.breaker_is_closed(BRK_F1) is False

    normal = process_control_scan(
        simulator, event=BreakerMqttEvent(scenario=grid.NORMAL), timestamp=0.35
    )
    assert normal.events == ()
    assert grid.breaker_is_closed(BRK_R1) is True
    assert grid.breaker_is_closed(BRK_F1) is False
    assert simulator.controllers[BRK_R1].tripped is True

    reset = process_control_scan(
        simulator,
        event=BreakerMqttEvent(command="RESET", breaker_name=BRK_R1),
        timestamp=0.40,
    )
    assert [e["event"] for e in reset.events] == ["RESET"]
    assert reset.events[0]["position"] == "CLOSED"
    assert reset.statuses[BRK_R1]["state"] == "CLOSED"
    assert grid.breaker_is_closed(BRK_R1) is True


def test_events_have_unique_identity_scan_time_and_nonretained_mqtt_contract() -> None:
    simulator = ControlledPandapowerSimulator(ReferenceFeederGrid.build(seed=1))
    client = FakeClient()
    pickup = process_control_scan(
        simulator,
        event=BreakerMqttEvent(scenario="TAIL_OVERCURRENT_TEST"),
        timestamp=0.0,
    )
    assert len({event["event_id"] for event in pickup.events}) == len(pickup.events)
    for event in pickup.events:
        assert event["ied"] == "IED_" + event["breaker"].removeprefix("BRK_")
        assert event["scan_monotonic_s"] == 0.0
        json.dumps(event, allow_nan=False)
        publish_ied_event(client, event)
    for topic, payload, qos, retain in client.published:
        assert topic == IED_EVENT_TOPIC
        assert json.loads(payload)["event_id"]
        assert qos == 0
        assert retain is False


def test_failed_operator_open_does_not_disable_protection_of_closed_switch() -> None:
    grid = ReferenceFeederGrid.build(seed=1)
    simulator = ControlledPandapowerSimulator(grid)
    grid.set_scenario(grid.R1_OPENING_FAILURE_TEST)
    first = process_control_scan(
        simulator,
        event=BreakerMqttEvent(command="OPEN", breaker_name=BRK_R1),
        timestamp=0.0,
    )
    assert first.command_accepted is True
    assert [e["event"] for e in events_for(first, BRK_R1)] == [
        "OPERATION_REQUEST", "POSITION_FEEDBACK", "PICKUP", "TIMING_STARTED"
    ]
    assert first.statuses[BRK_R1]["state"] == "CLOSED"
    assert grid.breaker_is_closed(BRK_R1) is True

    trip = process_control_scan(simulator, timestamp=0.10)
    assert [e["event"] for e in events_for(trip, BRK_R1)] == [
        "TRIP_REQUEST", "POSITION_FEEDBACK"
    ]
    assert simulator.controllers[BRK_R1].tripped is True
    assert grid.breaker_is_closed(BRK_R1) is True
