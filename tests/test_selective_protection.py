import json

from src.breaker_control import BreakerController
from src.power_grid import ReferenceFeederGrid
from src.power_sim import BRK_F1, BRK_R1, ControlledPandapowerSimulator


def bus_by_name(payload: dict[str, object], name: str) -> dict[str, object]:
    return next(bus for bus in payload["buses"] if bus["name"] == name)


def make_tail_overcurrent_simulator() -> ControlledPandapowerSimulator:
    grid = ReferenceFeederGrid.build(seed=1)
    assert grid.set_scenario(grid.TAIL_OVERCURRENT_TEST) is True
    return ControlledPandapowerSimulator(grid)


def trip_r1() -> ControlledPandapowerSimulator:
    simulator = make_tail_overcurrent_simulator()
    simulator.control_step(timestamp=0.00)
    simulator.control_step(timestamp=0.10)
    return simulator


def test_reference_settings_use_current_ka_and_selective_delays() -> None:
    simulator = make_tail_overcurrent_simulator()

    f1 = simulator.controllers[BRK_F1]
    r1 = simulator.controllers[BRK_R1]
    assert f1.pickup_ka == 0.20
    assert f1.trip_delay_s == 0.300
    assert r1.pickup_ka == 0.20
    assert r1.trip_delay_s == 0.100


def test_r1_primary_trip_keeps_remote_point_and_f1_energized() -> None:
    simulator = make_tail_overcurrent_simulator()

    pickup = simulator.control_step(timestamp=0.00)
    head_current = simulator.grid.breaker_current_ka(BRK_F1)
    tail_current = simulator.grid.breaker_current_ka(BRK_R1)
    assert head_current is not None and head_current >= 0.20
    assert tail_current is not None and tail_current >= 0.20
    assert simulator.controllers[BRK_R1].tripped is False

    before_trip = simulator.control_step(timestamp=0.099)
    assert simulator.controllers[BRK_R1].tripped is False
    primary_trip = simulator.control_step(timestamp=0.10)

    assert simulator.controllers[BRK_F1].tripped is False
    assert simulator.controllers[BRK_R1].tripped is True
    assert simulator.grid.breaker_is_closed(BRK_F1) is True
    assert simulator.grid.breaker_is_closed(BRK_R1) is False
    assert bus_by_name(primary_trip, simulator.grid.BUS_R1_REMOTE)[
        "energized"
    ] is True
    ss1 = bus_by_name(primary_trip, simulator.grid.BUS_SS1_LV)
    assert ss1["vm_pu"] is None
    assert ss1["energized"] is False
    assert ss1["quality"] == "NOT_ENERGIZED"
    for payload in (pickup, before_trip, primary_trip):
        json.dumps(payload, allow_nan=False)


def test_f1_timer_resets_after_r1_clears_solved_tail_current() -> None:
    simulator = make_tail_overcurrent_simulator()

    simulator.control_step(timestamp=0.00)
    simulator.control_step(timestamp=0.10)
    after_clear = simulator.control_step(timestamp=0.15)
    after_f1_delay = simulator.control_step(timestamp=0.30)

    assert simulator.controllers[BRK_R1].tripped is True
    assert simulator.grid.breaker_current_ka(BRK_R1) is None
    assert simulator.controllers[BRK_F1].tripped is False
    assert simulator.controllers[BRK_F1].state == BreakerController.CLOSED
    assert simulator.grid.breaker_is_closed(BRK_F1) is True
    assert bus_by_name(after_clear, simulator.grid.BUS_R1_REMOTE)[
        "energized"
    ] is True
    assert bus_by_name(after_f1_delay, simulator.grid.BUS_R1_REMOTE)[
        "energized"
    ] is True
    for payload in (after_clear, after_f1_delay):
        json.dumps(payload, allow_nan=False)


def test_r1_requires_reset_then_close_after_trip() -> None:
    simulator = trip_r1()
    assert simulator.grid.set_scenario(simulator.grid.NORMAL) is True
    controller = simulator.controllers[BRK_R1]

    assert controller.tripped is True
    assert simulator.command_breaker(BRK_R1, "CLOSE") is False
    assert controller.state == BreakerController.OPEN
    assert simulator.command_breaker(BRK_R1, "RESET") is True
    assert controller.tripped is False
    assert controller.state == BreakerController.OPEN

    after_reset = simulator.control_step(timestamp=0.15)
    assert simulator.grid.breaker_is_closed(BRK_R1) is False
    assert bus_by_name(after_reset, simulator.grid.BUS_SS1_LV)[
        "energized"
    ] is False

    assert simulator.command_breaker(BRK_R1, "CLOSE") is True
    assert simulator.grid.breaker_is_closed(BRK_R1) is False

    restored = simulator.control_step(timestamp=0.20)
    assert simulator.grid.breaker_is_closed(BRK_F1) is True
    assert simulator.grid.breaker_is_closed(BRK_R1) is True
    assert bus_by_name(restored, simulator.grid.BUS_R1_REMOTE)[
        "energized"
    ] is True
    assert bus_by_name(restored, simulator.grid.BUS_SS1_LV)[
        "energized"
    ] is True
    json.dumps(restored, allow_nan=False)
