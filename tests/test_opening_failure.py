"""Solved-current primary and backup behavior with failed R1 actuation."""

import json

import pytest

from src.power_grid import ReferenceFeederGrid
from src.power_sim import BRK_F1, BRK_R1, BreakerMqttEvent, ControlledPandapowerSimulator, process_control_scan


def scan(simulator, timestamp, event=None, *, vary_load=False):
    return process_control_scan(
        simulator, event=event, timestamp=timestamp, vary_load=vary_load
    )


def test_failure_scenario_uses_tail_inputs_and_refuses_only_r1_open() -> None:
    grid = ReferenceFeederGrid.build(seed=1)
    tail = grid.SCENARIO_INPUTS[grid.TAIL_OVERCURRENT_TEST]
    failure = grid.SCENARIO_INPUTS[grid.R1_OPENING_FAILURE_TEST]
    assert (failure.source_voltage_pu, failure.load_multiplier) == (
        tail.source_voltage_pu, tail.load_multiplier
    )
    assert failure.refuse_open_breaker == BRK_R1
    assert grid.set_scenario(grid.R1_OPENING_FAILURE_TEST)
    assert float(grid.net.load.at[grid.load_idx, "p_mw"]) == 10.0

    grid.set_breaker_closed(BRK_R1, False)
    assert grid.breaker_is_closed(BRK_R1) is True
    grid.set_breaker_closed(BRK_F1, False)
    assert grid.breaker_is_closed(BRK_F1) is False
    assert grid.set_scenario(grid.NORMAL)
    assert grid.breaker_is_closed(BRK_R1) is True
    assert grid.breaker_is_closed(BRK_F1) is False


@pytest.mark.parametrize("scenario_time", [0.95, 1.0, 1.05])
def test_failed_r1_open_leaves_current_for_f1_backup_at_300_ms(
    scenario_time,
) -> None:
    grid = ReferenceFeederGrid.build(seed=1)
    simulator = ControlledPandapowerSimulator(grid)
    scan(simulator, 0.0, vary_load=True)
    if scenario_time > 1.0:
        scan(simulator, 1.0, vary_load=True)
    variation_steps = grid.step_count
    next_publication = 1.0 if scenario_time <= 1.0 else 2.0

    def scheduled_scan(simulator, timestamp, event=None):
        nonlocal next_publication
        now = scenario_time + timestamp
        publish_due = now >= next_publication
        if publish_due:
            next_publication += 1.0
        return scan(simulator, now, event, vary_load=publish_due)

    pickup = scheduled_scan(
        simulator, 0.0,
        BreakerMqttEvent(scenario=grid.R1_OPENING_FAILURE_TEST),
    )
    assert pickup.scenario_accepted is True
    assert grid.breaker_current_ka(BRK_R1) >= 0.20
    assert simulator.ieds[BRK_R1].measurements.position == "CLOSED"

    scheduled_scan(simulator, 0.05)
    primary = scheduled_scan(simulator, 0.10)
    assert simulator.controllers[BRK_R1].tripped is True
    assert simulator.controllers[BRK_F1].tripped is False
    assert grid.breaker_is_closed(BRK_R1) is True
    assert primary.statuses[BRK_R1]["state"] == "CLOSED"
    assert primary.statuses[BRK_R1]["tripped"] is True
    assert grid.breaker_current_ka(BRK_R1) >= 0.20
    assert next(bus for bus in primary.telemetry["buses"]
                if bus["name"] == grid.BUS_SS1_LV)["energized"] is True

    for timestamp in (0.15, 0.20, 0.25):
        before_backup = scheduled_scan(simulator, timestamp)
        assert simulator.controllers[BRK_F1].tripped is False
        assert grid.breaker_is_closed(BRK_F1) is True
        assert grid.breaker_current_ka(BRK_F1) >= 0.20
        json.dumps(before_backup.telemetry, allow_nan=False)

    backup = scheduled_scan(simulator, 0.30)
    assert simulator.controllers[BRK_F1].tripped is True
    assert grid.breaker_is_closed(BRK_F1) is False
    assert grid.breaker_is_closed(BRK_R1) is True
    assert backup.statuses[BRK_F1]["state"] == "OPEN"
    assert BRK_R1 not in backup.statuses
    assert next(bus for bus in backup.telemetry["buses"]
                if bus["name"] == grid.BUS_SS1_LV)["quality"] == "NOT_ENERGIZED"
    json.dumps(backup.telemetry, allow_nan=False)
    assert grid.step_count == variation_steps

    for breaker in (BRK_R1, BRK_F1):
        rejected = scheduled_scan(
            simulator, 0.31,
            BreakerMqttEvent(command="CLOSE", breaker_name=breaker),
        )
        assert rejected.command_accepted is False
        assert rejected.statuses[breaker]["tripped"] is True

    normal = scheduled_scan(simulator, 0.35, BreakerMqttEvent(scenario=grid.NORMAL))
    assert normal.scenario_accepted is True
    assert grid.breaker_is_closed(BRK_F1) is False
    assert grid.breaker_is_closed(BRK_R1) is True
    assert simulator.controllers[BRK_F1].tripped is True
    assert simulator.controllers[BRK_R1].tripped is True

    reset = scheduled_scan(
        simulator, 0.40,
        BreakerMqttEvent(command="RESET", breaker_name=BRK_R1),
    )
    assert reset.command_accepted is True
    assert reset.statuses[BRK_R1]["state"] == "CLOSED"
    assert reset.statuses[BRK_R1]["tripped"] is False
    assert grid.breaker_is_closed(BRK_R1) is True
    assert grid.breaker_is_closed(BRK_F1) is False

    reset_f1 = scheduled_scan(
        simulator, 0.45,
        BreakerMqttEvent(command="RESET", breaker_name=BRK_F1),
    )
    assert reset_f1.statuses[BRK_F1]["state"] == "OPEN"
    assert reset_f1.statuses[BRK_F1]["tripped"] is False
    # NORMAL removed refusal, but only an explicit operation moves R1.
    opened = scheduled_scan(
        simulator, 0.50,
        BreakerMqttEvent(command="OPEN", breaker_name=BRK_R1),
    )
    assert opened.statuses[BRK_R1]["state"] == "OPEN"
