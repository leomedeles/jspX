import json

import pytest

from src.breaker_control import BreakerController
from src.power_grid import ThreeBusGrid
from src.power_sim import ControlledPandapowerSimulator


def bus_by_name(payload: dict[str, object], name: str) -> dict[str, object]:
    return next(bus for bus in payload["buses"] if bus["name"] == name)


def protected_line_ends(
    grid: ThreeBusGrid, payload: dict[str, object]
) -> list[dict[str, object]]:
    return [
        line
        for line in payload["lines"]
        if line["line_idx"] == grid.protected_line_idx
    ]


def test_default_closed_breaker_energizes_downstream_section() -> None:
    grid = ThreeBusGrid.build(seed=1)

    payload = grid.solve()

    switch = grid.net.switch.loc[grid.breaker_switch_idx]
    assert bool(switch["closed"]) is True
    assert switch["et"] == "l"
    assert int(switch["bus"]) == int(
        grid.net.line.at[grid.protected_line_idx, "from_bus"]
    )
    assert int(switch["element"]) == grid.protected_line_idx
    assert bus_by_name(payload, "BUS1_LOAD")["energized"] is True
    assert bus_by_name(payload, "BUS2_LOAD")["energized"] is True
    assert grid.protected_line_loading_percent() > 0.0


def test_open_breaker_operates_switch_and_isolates_protected_path() -> None:
    grid = ThreeBusGrid.build(seed=1)
    controller = BreakerController()
    simulator = ControlledPandapowerSimulator(grid, controller)
    controller.open()

    payload = simulator.control_step(timestamp=0.0)

    assert grid.breaker_closed is False
    assert bus_by_name(payload, "BUS0_SLACK")["energized"] is True
    for line in protected_line_ends(grid, payload):
        assert line["p_mw"] == pytest.approx(0.0, abs=1e-12)
        assert line["i_ka"] == pytest.approx(0.0, abs=1e-12)
        assert line["loading_percent"] == pytest.approx(0.0, abs=1e-12)
        assert line["energized"] is False
        assert line["quality"] == "NOT_ENERGIZED"
    for bus_name in ("BUS1_LOAD", "BUS2_LOAD"):
        bus = bus_by_name(payload, bus_name)
        assert bus["vm_pu"] is None
        assert bus["energized"] is False
        assert bus["quality"] == "NOT_ENERGIZED"


def test_protection_trip_opens_physical_switch_in_same_control_step() -> None:
    grid = ThreeBusGrid.build(seed=1)
    grid.net.line.at[grid.protected_line_idx, "max_i_ka"] = 0.02
    controller = BreakerController()
    simulator = ControlledPandapowerSimulator(grid, controller)

    simulator.control_step(timestamp=0.00)
    payload = simulator.control_step(timestamp=0.10)

    assert controller.tripped is True
    assert controller.state == controller.OPEN
    assert grid.breaker_closed is False
    assert payload["breaker"]["tripped"] is True
    assert all(
        line["loading_percent"] == pytest.approx(0.0, abs=1e-12)
        for line in protected_line_ends(grid, payload)
    )


def test_disconnected_telemetry_is_strict_json() -> None:
    grid = ThreeBusGrid.build(seed=1)
    grid.set_breaker_closed(False)

    payload = grid.solve()

    encoded = json.dumps(payload, allow_nan=False)
    assert '"vm_pu": null' in encoded
    assert bus_by_name(payload, "BUS1_LOAD")["vm_pu"] is None
    assert bus_by_name(payload, "BUS2_LOAD")["vm_pu"] is None
