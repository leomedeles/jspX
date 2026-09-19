import numpy as np
import pytest

from src.breaker_control import BreakerController
from src.power_grid import ThreeBusGrid
from src.power_sim import (
    SCENARIO_COMMAND_TOPIC,
    BreakerMqttEventQueue,
    ControlledPandapowerSimulator,
    process_control_scan,
)


class FakeMessage:
    def __init__(self, payload: bytes) -> None:
        self.topic = SCENARIO_COMMAND_TOPIC
        self.payload = payload


def make_simulator() -> tuple[
    ControlledPandapowerSimulator, BreakerMqttEventQueue
]:
    return (
        ControlledPandapowerSimulator(
            ThreeBusGrid.build(seed=1), BreakerController()
        ),
        BreakerMqttEventQueue(),
    )


def queue_scenario(events: BreakerMqttEventQueue, payload: bytes) -> None:
    events.on_message(None, None, FakeMessage(payload))


@pytest.mark.parametrize(
    ("scenario", "source_voltage", "load_multiplier"),
    [
        (ThreeBusGrid.NORMAL, 1.0, 1.0),
        (ThreeBusGrid.OVERCURRENT, 1.0, 5.0),
        (ThreeBusGrid.UNDERVOLTAGE, 0.90, 1.0),
        (ThreeBusGrid.DOWNSTREAM_OVERCURRENT, 1.0, 1.0),
    ],
)
def test_valid_scenario_is_accepted_and_applied_on_control_scan(
    scenario: str, source_voltage: float, load_multiplier: float
) -> None:
    simulator, events = make_simulator()
    queue_scenario(events, scenario.encode("utf-8"))

    assert simulator.grid.scenario == ThreeBusGrid.NORMAL
    result = process_control_scan(
        simulator, event=events.pop(), timestamp=0.0
    )

    assert result.scenario == scenario
    assert result.scenario_accepted is True
    assert simulator.grid.scenario == scenario
    assert simulator.grid.net.ext_grid.iloc[0]["vm_pu"] == pytest.approx(
        source_voltage
    )
    assert simulator.grid.net.load["p_mw"].to_numpy() == pytest.approx(
        simulator.grid.base_p_mw * load_multiplier
    )
    assert simulator.grid.net.load["q_mvar"].to_numpy() == pytest.approx(
        simulator.grid.base_q_mvar * load_multiplier
    )


def test_overcurrent_is_real_loading_and_trips_after_100_ms() -> None:
    simulator, events = make_simulator()
    original_rating = float(
        simulator.grid.net.line.at[
            simulator.grid.protected_line_idx, "max_i_ka"
        ]
    )
    queue_scenario(events, b"OVERCURRENT")

    pickup = process_control_scan(
        simulator, event=events.pop(), timestamp=0.0, vary_load=True
    )
    loading_at_pickup = simulator.grid.protected_line_loading_percent()

    assert pickup.scenario_accepted is True
    assert loading_at_pickup is not None
    assert loading_at_pickup > simulator.controller.pickup_percent
    assert simulator.controller.tripped is False
    assert float(
        simulator.grid.net.line.at[
            simulator.grid.protected_line_idx, "max_i_ka"
        ]
    ) == pytest.approx(original_rating)

    process_control_scan(simulator, timestamp=0.099)
    assert simulator.controller.tripped is False

    trip = process_control_scan(simulator, timestamp=0.100)
    assert trip.status is not None
    assert simulator.controller.tripped is True
    assert simulator.controller.trip_reason == "overcurrent"
    assert simulator.grid.breaker_closed is False


def test_undervoltage_asserts_alarm_and_normal_clears_it() -> None:
    simulator, events = make_simulator()
    queue_scenario(events, b"UNDERVOLTAGE")

    undervoltage = process_control_scan(
        simulator, event=events.pop(), timestamp=0.0
    )
    depressed_voltages = simulator.grid.downstream_voltages_pu()

    assert undervoltage.scenario_accepted is True
    assert all(voltage is not None for voltage in depressed_voltages)
    assert min(depressed_voltages) < 0.92
    assert simulator.controller.undervoltage_alarm is True
    assert simulator.controller.tripped is False
    assert simulator.grid.breaker_closed is True

    queue_scenario(events, b"NORMAL")
    normal = process_control_scan(
        simulator, event=events.pop(), timestamp=0.05
    )
    restored_voltages = simulator.grid.downstream_voltages_pu()

    assert normal.scenario_accepted is True
    assert all(voltage is not None for voltage in restored_voltages)
    assert min(restored_voltages) >= 0.94
    assert simulator.controller.undervoltage_alarm is False
    assert simulator.controller.tripped is False
    assert simulator.grid.breaker_closed is True


def test_normal_does_not_reset_trip_latch_or_close_breaker() -> None:
    simulator, events = make_simulator()
    queue_scenario(events, b"OVERCURRENT")
    process_control_scan(simulator, event=events.pop(), timestamp=0.0)
    process_control_scan(simulator, timestamp=0.100)
    assert simulator.controller.tripped is True
    assert simulator.grid.breaker_closed is False

    queue_scenario(events, b"NORMAL")
    normal = process_control_scan(
        simulator, event=events.pop(), timestamp=0.15
    )

    assert normal.scenario_accepted is True
    assert simulator.grid.scenario == ThreeBusGrid.NORMAL
    assert simulator.controller.tripped is True
    assert simulator.controller.state == BreakerController.OPEN
    assert simulator.grid.breaker_closed is False
    assert simulator.grid.net.load["p_mw"].to_numpy() == pytest.approx(
        simulator.grid.base_p_mw
    )


@pytest.mark.parametrize(
    "invalid_payload",
    [b"normal", b"NORMAL\n", b"UNKNOWN", b"", b"\xff"],
)
def test_invalid_scenario_leaves_prior_scenario_and_plant_unchanged(
    invalid_payload: bytes,
) -> None:
    simulator, events = make_simulator()
    queue_scenario(events, b"UNDERVOLTAGE")
    process_control_scan(simulator, event=events.pop(), timestamp=0.0)

    prior_scenario = simulator.grid.scenario
    prior_source_voltage = simulator.grid.net.ext_grid["vm_pu"].to_numpy().copy()
    prior_p_mw = simulator.grid.net.load["p_mw"].to_numpy().copy()
    prior_q_mvar = simulator.grid.net.load["q_mvar"].to_numpy().copy()
    prior_breaker_position = simulator.grid.breaker_closed
    prior_controller = simulator.controller.snapshot()

    queue_scenario(events, invalid_payload)
    assert simulator.grid.scenario == prior_scenario
    np.testing.assert_array_equal(
        simulator.grid.net.ext_grid["vm_pu"].to_numpy(), prior_source_voltage
    )
    np.testing.assert_array_equal(
        simulator.grid.net.load["p_mw"].to_numpy(), prior_p_mw
    )
    np.testing.assert_array_equal(
        simulator.grid.net.load["q_mvar"].to_numpy(), prior_q_mvar
    )
    assert simulator.grid.breaker_closed is prior_breaker_position
    assert simulator.controller.snapshot() == prior_controller

    result = process_control_scan(
        simulator, event=events.pop(), timestamp=0.05
    )

    assert result.scenario_accepted is False
    assert simulator.grid.scenario == prior_scenario
    np.testing.assert_array_equal(
        simulator.grid.net.ext_grid["vm_pu"].to_numpy(), prior_source_voltage
    )
    np.testing.assert_array_equal(
        simulator.grid.net.load["p_mw"].to_numpy(), prior_p_mw
    )
    np.testing.assert_array_equal(
        simulator.grid.net.load["q_mvar"].to_numpy(), prior_q_mvar
    )
    assert simulator.grid.breaker_closed is prior_breaker_position
    assert simulator.controller.snapshot() == prior_controller
