import pytest

from src.breaker_control import BreakerController
from src.power_grid import ReferenceFeederGrid
from src.power_sim import (
    BRK_F1,
    BRK_R1,
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
        ControlledPandapowerSimulator(ReferenceFeederGrid.build(seed=1)),
        BreakerMqttEventQueue(),
    )


def queue_scenario(events: BreakerMqttEventQueue, payload: bytes) -> None:
    events.on_message(None, None, FakeMessage(payload))


@pytest.mark.parametrize(
    ("scenario", "source_voltage", "load_multiplier"),
    [
        (ReferenceFeederGrid.NORMAL, 1.0, 1.0),
        (ReferenceFeederGrid.TAIL_OVERCURRENT_TEST, 1.0, 5.0),
        (ReferenceFeederGrid.LOW_SOURCE_VOLTAGE, 0.90, 1.0),
    ],
)
def test_valid_scenario_is_accepted_and_applied_on_control_scan(
    scenario: str, source_voltage: float, load_multiplier: float
) -> None:
    simulator, events = make_simulator()
    queue_scenario(events, scenario.encode("utf-8"))

    result = process_control_scan(
        simulator, event=events.pop(), timestamp=0.0
    )

    assert result.scenario == scenario
    assert result.scenario_accepted is True
    assert simulator.grid.scenario == scenario
    assert float(simulator.grid.net.ext_grid.iloc[0]["vm_pu"]) == pytest.approx(
        source_voltage
    )
    load = simulator.grid.net.load.loc[simulator.grid.load_idx]
    assert float(load["p_mw"]) == pytest.approx(
        simulator.grid.base_p_mw * load_multiplier
    )
    assert float(load["q_mvar"]) == pytest.approx(
        simulator.grid.base_q_mvar * load_multiplier
    )


def test_tail_overcurrent_uses_solved_tail_current() -> None:
    simulator, events = make_simulator()
    original_rating = float(
        simulator.grid.net.line.at[
            simulator.grid.line_indices[simulator.grid.L2_FEEDER_TAIL],
            "max_i_ka",
        ]
    )
    queue_scenario(events, b"TAIL_OVERCURRENT_TEST")

    pickup = process_control_scan(
        simulator, event=events.pop(), timestamp=0.0
    )
    tail_current_ka = simulator.grid.breaker_current_ka(BRK_R1)

    assert pickup.scenario_accepted is True
    assert tail_current_ka is not None
    assert tail_current_ka >= simulator.controllers[BRK_R1].pickup_ka
    assert simulator.controllers[BRK_R1].tripped is False
    assert float(
        simulator.grid.net.line.at[
            simulator.grid.line_indices[simulator.grid.L2_FEEDER_TAIL],
            "max_i_ka",
        ]
    ) == pytest.approx(original_rating)


def test_low_source_voltage_asserts_f1_alarm_and_normal_clears_it() -> None:
    simulator, events = make_simulator()
    queue_scenario(events, b"LOW_SOURCE_VOLTAGE")

    low_voltage = process_control_scan(
        simulator, event=events.pop(), timestamp=0.0
    )
    source_mv_voltage = simulator.grid.bus_voltage_pu(
        simulator.grid.BUS_MV_SOURCE
    )

    assert low_voltage.scenario_accepted is True
    assert source_mv_voltage is not None
    assert source_mv_voltage < 0.92
    assert simulator.controllers[BRK_F1].undervoltage_alarm is True
    assert simulator.controllers[BRK_R1].undervoltage_alarm is False
    assert simulator.controllers[BRK_F1].tripped is False
    assert simulator.grid.breaker_is_closed(BRK_F1) is True

    queue_scenario(events, b"NORMAL")
    normal = process_control_scan(
        simulator, event=events.pop(), timestamp=0.05
    )
    restored_voltage = simulator.grid.bus_voltage_pu(
        simulator.grid.BUS_MV_SOURCE
    )

    assert normal.scenario_accepted is True
    assert restored_voltage is not None
    assert restored_voltage >= 0.94
    assert simulator.controllers[BRK_F1].undervoltage_alarm is False
    assert simulator.controllers[BRK_F1].tripped is False
    assert simulator.grid.breaker_is_closed(BRK_F1) is True


def test_normal_does_not_reset_trip_latch_or_close_breaker() -> None:
    simulator, events = make_simulator()
    queue_scenario(events, b"TAIL_OVERCURRENT_TEST")
    process_control_scan(simulator, event=events.pop(), timestamp=0.0)
    process_control_scan(simulator, timestamp=0.100)
    assert simulator.controllers[BRK_R1].tripped is True
    assert simulator.grid.breaker_is_closed(BRK_R1) is False

    queue_scenario(events, b"NORMAL")
    normal = process_control_scan(
        simulator, event=events.pop(), timestamp=0.15
    )

    assert normal.scenario_accepted is True
    assert simulator.grid.scenario == ReferenceFeederGrid.NORMAL
    assert simulator.controllers[BRK_R1].tripped is True
    assert simulator.controllers[BRK_R1].state == BreakerController.OPEN
    assert simulator.grid.breaker_is_closed(BRK_R1) is False
    load = simulator.grid.net.load.loc[simulator.grid.load_idx]
    assert float(load["p_mw"]) == pytest.approx(simulator.grid.base_p_mw)
    assert float(load["q_mvar"]) == pytest.approx(simulator.grid.base_q_mvar)


@pytest.mark.parametrize(
    "invalid_payload",
    [
        b"normal",
        b"NORMAL\n",
        b"OVERCURRENT",
        b"UNDERVOLTAGE",
        b"DOWNSTREAM_OVERCURRENT",
        b"UNKNOWN",
        b"",
        b"\xff",
    ],
)
def test_invalid_scenario_leaves_prior_scenario_and_plant_unchanged(
    invalid_payload: bytes,
) -> None:
    simulator, events = make_simulator()
    queue_scenario(events, b"LOW_SOURCE_VOLTAGE")
    process_control_scan(simulator, event=events.pop(), timestamp=0.0)

    prior_scenario = simulator.grid.scenario
    prior_source_voltage = float(simulator.grid.net.ext_grid.iloc[0]["vm_pu"])
    prior_load = simulator.grid.net.load.loc[
        simulator.grid.load_idx, ["p_mw", "q_mvar"]
    ].copy()
    prior_breakers = {
        name: simulator.grid.breaker_is_closed(name)
        for name in (BRK_F1, BRK_R1)
    }
    prior_controllers = {
        name: controller.snapshot()
        for name, controller in simulator.controllers.items()
    }

    queue_scenario(events, invalid_payload)
    result = process_control_scan(
        simulator, event=events.pop(), timestamp=0.05
    )

    assert result.scenario_accepted is False
    assert simulator.grid.scenario == prior_scenario
    assert float(simulator.grid.net.ext_grid.iloc[0]["vm_pu"]) == pytest.approx(
        prior_source_voltage
    )
    assert simulator.grid.net.load.loc[
        simulator.grid.load_idx, ["p_mw", "q_mvar"]
    ].equals(prior_load)
    assert {
        name: simulator.grid.breaker_is_closed(name)
        for name in (BRK_F1, BRK_R1)
    } == prior_breakers
    assert {
        name: controller.snapshot()
        for name, controller in simulator.controllers.items()
    } == prior_controllers
