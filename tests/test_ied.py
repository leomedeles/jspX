"""IED bindings and the request-to-physical-feedback boundary."""

from src.ied import IED_F1, IED_R1, REFERENCE_IED_CONFIGS
from src.power_grid import ReferenceFeederGrid
from src.power_sim import BRK_F1, BRK_R1, BreakerMqttEvent, ControlledPandapowerSimulator, process_control_scan


def test_reference_ieds_bind_canonical_current_voltage_and_position() -> None:
    grid = ReferenceFeederGrid.build(seed=1)
    simulator = ControlledPandapowerSimulator(grid)

    assert REFERENCE_IED_CONFIGS == (IED_F1, IED_R1)
    assert (IED_F1.identity, IED_F1.breaker, IED_F1.current_breaker,
            IED_F1.voltage_bus, IED_F1.trip_delay_s, IED_F1.event_source) == (
        "IED_F1", BRK_F1, BRK_F1, grid.BUS_MV_SOURCE, 0.300, "IED_F1"
    )
    assert (IED_R1.identity, IED_R1.breaker, IED_R1.current_breaker,
            IED_R1.voltage_bus, IED_R1.trip_delay_s, IED_R1.event_source) == (
        "IED_R1", BRK_R1, BRK_R1, grid.BUS_R1_REMOTE, 0.100, "IED_R1"
    )
    assert IED_F1.undervoltage_action is True
    assert IED_R1.undervoltage_action is False

    simulator.control_step(timestamp=0.0)
    for name, ied in simulator.ieds.items():
        assert ied.measurements.current_ka == grid.breaker_current_ka(name)
        assert ied.measurements.voltage_pu == grid.bus_voltage_pu(ied.config.voltage_bus)
        assert ied.measurements.position == "CLOSED"


def test_accepted_open_is_attempted_once_and_status_uses_physical_feedback(monkeypatch) -> None:
    grid = ReferenceFeederGrid.build(seed=1)
    simulator = ControlledPandapowerSimulator(grid)
    attempted = []
    actual_set = grid.set_breaker_closed

    def refuse_r1_open(name: str, closed: bool) -> None:
        attempted.append((name, closed))
        if name != BRK_R1 or closed:
            actual_set(name, closed)

    monkeypatch.setattr(grid, "set_breaker_closed", refuse_r1_open)
    result = process_control_scan(
        simulator,
        event=BreakerMqttEvent(command="OPEN", breaker_name=BRK_R1),
        timestamp=0.0,
    )

    assert result.command_accepted is True
    assert attempted == [(BRK_R1, False)]
    assert simulator.controllers[BRK_R1].state == "OPEN"  # requested state
    assert grid.breaker_is_closed(BRK_R1) is True
    assert result.statuses[BRK_R1]["state"] == "CLOSED"
    assert next(bus for bus in result.telemetry["buses"]
                if bus["name"] == grid.BUS_SS1_LV)["energized"] is True

    process_control_scan(simulator, timestamp=0.05)
    assert attempted == [(BRK_R1, False)]
