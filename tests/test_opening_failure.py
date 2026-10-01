"""Solved-current primary and backup behavior with failed R1 actuation."""

import json

from src.power_grid import ReferenceFeederGrid
from src.power_sim import BRK_F1, BRK_R1, BreakerMqttEvent, ControlledPandapowerSimulator, process_control_scan


def scan(simulator, timestamp, event=None):
    return process_control_scan(simulator, event=event, timestamp=timestamp)


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


def test_failed_r1_open_leaves_current_for_f1_backup_at_300_ms() -> None:
    grid = ReferenceFeederGrid.build(seed=1)
    simulator = ControlledPandapowerSimulator(grid)
    pickup = scan(
        simulator, 0.0,
        BreakerMqttEvent(scenario=grid.R1_OPENING_FAILURE_TEST),
    )
    assert pickup.scenario_accepted is True
    assert grid.breaker_current_ka(BRK_R1) >= 0.20
    assert simulator.ieds[BRK_R1].measurements.position == "CLOSED"

    scan(simulator, 0.05)
    primary = scan(simulator, 0.10)
    assert simulator.controllers[BRK_R1].tripped is True
    assert simulator.controllers[BRK_F1].tripped is False
    assert grid.breaker_is_closed(BRK_R1) is True
    assert primary.statuses[BRK_R1]["state"] == "CLOSED"
    assert primary.statuses[BRK_R1]["tripped"] is True
    assert grid.breaker_current_ka(BRK_R1) >= 0.20
    assert next(bus for bus in primary.telemetry["buses"]
                if bus["name"] == grid.BUS_SS1_LV)["energized"] is True

    for timestamp in (0.15, 0.20, 0.25):
        before_backup = scan(simulator, timestamp)
        assert simulator.controllers[BRK_F1].tripped is False
        assert grid.breaker_is_closed(BRK_F1) is True
        assert grid.breaker_current_ka(BRK_F1) >= 0.20
        json.dumps(before_backup.telemetry, allow_nan=False)

    backup = scan(simulator, 0.30)
    assert simulator.controllers[BRK_F1].tripped is True
    assert grid.breaker_is_closed(BRK_F1) is False
    assert grid.breaker_is_closed(BRK_R1) is True
    assert backup.statuses[BRK_F1]["state"] == "OPEN"
    assert BRK_R1 not in backup.statuses
    assert next(bus for bus in backup.telemetry["buses"]
                if bus["name"] == grid.BUS_SS1_LV)["quality"] == "NOT_ENERGIZED"
    json.dumps(backup.telemetry, allow_nan=False)

    normal = scan(simulator, 0.35, BreakerMqttEvent(scenario=grid.NORMAL))
    assert normal.scenario_accepted is True
    assert grid.breaker_is_closed(BRK_F1) is False
    assert grid.breaker_is_closed(BRK_R1) is True
    assert simulator.controllers[BRK_F1].tripped is True
    assert simulator.controllers[BRK_R1].tripped is True

    reset = scan(
        simulator, 0.40,
        BreakerMqttEvent(command="RESET", breaker_name=BRK_R1),
    )
    assert reset.command_accepted is True
    assert reset.statuses[BRK_R1]["state"] == "CLOSED"
    assert reset.statuses[BRK_R1]["tripped"] is False
    assert grid.breaker_is_closed(BRK_R1) is True
    assert grid.breaker_is_closed(BRK_F1) is False
