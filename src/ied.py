"""Reusable simulated IED with explicit reference-feeder bindings."""

from __future__ import annotations

from dataclasses import dataclass

if __package__:
    from .breaker_control import BreakerController
else:
    from breaker_control import BreakerController


@dataclass(frozen=True)
class IEDConfig:
    identity: str
    breaker: str
    current_breaker: str
    voltage_bus: str
    pickup_ka: float
    trip_delay_s: float
    undervoltage_action: bool
    event_source: str


IED_F1 = IEDConfig(
    identity="IED_F1",
    breaker="BRK_F1",
    current_breaker="BRK_F1",
    voltage_bus="BUS_MV_SOURCE",
    pickup_ka=0.20,
    trip_delay_s=0.300,
    undervoltage_action=True,
    event_source="IED_F1",
)
IED_R1 = IEDConfig(
    identity="IED_R1",
    breaker="BRK_R1",
    current_breaker="BRK_R1",
    voltage_bus="BUS_R1_REMOTE",
    pickup_ka=0.20,
    trip_delay_s=0.100,
    undervoltage_action=False,
    event_source="IED_R1",
)
REFERENCE_IED_CONFIGS = (IED_F1, IED_R1)


@dataclass(frozen=True)
class IEDMeasurements:
    current_ka: float | None
    voltage_pu: float | None
    position: str


class SimulatedIED:
    """Bind one transport-independent controller to named plant measurements."""

    def __init__(
        self, config: IEDConfig, controller: BreakerController | None = None
    ) -> None:
        self.config = config
        self.controller = controller or BreakerController(
            pickup_ka=config.pickup_ka,
            trip_delay_s=config.trip_delay_s,
        )
        self.measurements: IEDMeasurements | None = None

    def evaluate(self, grid, timestamp: float) -> dict[str, object]:
        self.measurements = IEDMeasurements(
            current_ka=grid.breaker_current_ka(self.config.current_breaker),
            voltage_pu=grid.bus_voltage_pu(self.config.voltage_bus),
            position=(
                BreakerController.CLOSED
                if grid.breaker_is_closed(self.config.breaker)
                else BreakerController.OPEN
            ),
        )
        return self.controller.evaluate(
            current_ka=self.measurements.current_ka,
            voltages_pu=(self.measurements.voltage_pu,)
            if self.config.undervoltage_action
            else (),
            timestamp=timestamp,
            position_closed=self.measurements.position == BreakerController.CLOSED,
        )
