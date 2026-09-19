import json

from src.breaker_control import BreakerController
from src.power_grid import ThreeBusGrid
from src.power_sim import BRK_L1_SOURCE, BRK_L2, ControlledPandapowerSimulator


def bus_by_name(payload: dict[str, object], name: str) -> dict[str, object]:
    return next(bus for bus in payload["buses"] if bus["name"] == name)


def make_downstream_overcurrent_simulator() -> ControlledPandapowerSimulator:
    grid = ThreeBusGrid.build(seed=1)
    assert grid.set_scenario(ThreeBusGrid.DOWNSTREAM_OVERCURRENT) is True
    return ControlledPandapowerSimulator(grid, BreakerController())


def trip_both_breakers() -> ControlledPandapowerSimulator:
    simulator = make_downstream_overcurrent_simulator()
    simulator.control_step(timestamp=0.00)
    simulator.control_step(timestamp=0.10)
    simulator.control_step(timestamp=0.20)
    return simulator


def test_l2_primary_trip_keeps_bus1_energized() -> None:
    simulator = make_downstream_overcurrent_simulator()

    pickup = simulator.control_step(timestamp=0.00)
    assert simulator.controllers[BRK_L2].tripped is False
    before_trip = simulator.control_step(timestamp=0.099)
    assert simulator.controllers[BRK_L2].tripped is False
    primary_trip = simulator.control_step(timestamp=0.10)

    assert simulator.controllers[BRK_L1_SOURCE].tripped is False
    assert simulator.controllers[BRK_L2].tripped is True
    assert simulator.grid.breaker_closed is True
    assert simulator.grid.l2_breaker_closed is False
    assert bus_by_name(primary_trip, "BUS1_LOAD")["energized"] is True
    bus2 = bus_by_name(primary_trip, "BUS2_LOAD")
    assert bus2["vm_pu"] is None
    assert bus2["energized"] is False
    assert bus2["quality"] == "NOT_ENERGIZED"
    for payload in (pickup, before_trip, primary_trip):
        json.dumps(payload, allow_nan=False)


def test_persistent_condition_trips_l1_as_delayed_backup() -> None:
    simulator = make_downstream_overcurrent_simulator()

    simulator.control_step(timestamp=0.00)
    primary_trip = simulator.control_step(timestamp=0.10)
    assert simulator.controllers[BRK_L1_SOURCE].tripped is False
    before_backup = simulator.control_step(timestamp=0.199)
    assert simulator.controllers[BRK_L1_SOURCE].tripped is False
    backup_trip = simulator.control_step(timestamp=0.20)

    assert bus_by_name(primary_trip, "BUS1_LOAD")["energized"] is True
    assert simulator.controllers[BRK_L2].tripped is True
    assert simulator.controllers[BRK_L1_SOURCE].tripped is True
    assert simulator.grid.l2_breaker_closed is False
    assert simulator.grid.breaker_closed is False
    assert bus_by_name(backup_trip, "BUS1_LOAD")["energized"] is False
    assert bus_by_name(backup_trip, "BUS2_LOAD")["energized"] is False
    for payload in (primary_trip, before_backup, backup_trip):
        json.dumps(payload, allow_nan=False)


def test_both_breakers_require_reset_then_close_after_trip() -> None:
    simulator = trip_both_breakers()
    assert simulator.grid.set_scenario(ThreeBusGrid.NORMAL) is True

    for breaker_name in (BRK_L2, BRK_L1_SOURCE):
        controller = simulator.controllers[breaker_name]
        assert controller.tripped is True
        assert simulator.command_breaker(breaker_name, "CLOSE") is False
        assert controller.state == BreakerController.OPEN
        assert simulator.command_breaker(breaker_name, "RESET") is True
        assert controller.tripped is False
        assert controller.state == BreakerController.OPEN

    after_reset = simulator.control_step(timestamp=0.25)
    assert simulator.grid.breaker_closed is False
    assert simulator.grid.l2_breaker_closed is False
    json.dumps(after_reset, allow_nan=False)

    assert simulator.command_breaker(BRK_L1_SOURCE, "CLOSE") is True
    assert simulator.command_breaker(BRK_L2, "CLOSE") is True
    assert simulator.grid.breaker_closed is False
    assert simulator.grid.l2_breaker_closed is False

    restored = simulator.control_step(timestamp=0.30)
    assert simulator.grid.breaker_closed is True
    assert simulator.grid.l2_breaker_closed is True
    assert bus_by_name(restored, "BUS1_LOAD")["energized"] is True
    assert bus_by_name(restored, "BUS2_LOAD")["energized"] is True
    json.dumps(restored, allow_nan=False)
