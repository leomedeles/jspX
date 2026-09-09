"""Pure breaker control and protection state machine."""

from __future__ import annotations

import math
from collections.abc import Iterable


class BreakerController:
    """Own breaker state, overcurrent tripping, and undervoltage alarming."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"

    def __init__(
        self,
        *,
        initial_state: str = CLOSED,
        pickup_percent: float = 120.0,
        trip_delay_s: float = 0.100,
        undervoltage_assert_pu: float = 0.92,
        undervoltage_clear_pu: float = 0.94,
    ) -> None:
        if initial_state not in (self.OPEN, self.CLOSED):
            raise ValueError("initial_state must be OPEN or CLOSED")
        if pickup_percent <= 0:
            raise ValueError("pickup_percent must be positive")
        if trip_delay_s < 0:
            raise ValueError("trip_delay_s must not be negative")
        if undervoltage_assert_pu >= undervoltage_clear_pu:
            raise ValueError(
                "undervoltage_assert_pu must be below undervoltage_clear_pu"
            )

        self.pickup_percent = float(pickup_percent)
        self.trip_delay_s = float(trip_delay_s)
        self.undervoltage_assert_pu = float(undervoltage_assert_pu)
        self.undervoltage_clear_pu = float(undervoltage_clear_pu)

        self.state = initial_state
        self.tripped = False
        self.undervoltage_alarm = False
        self.trip_reason: str | None = None
        self._overcurrent_started_at: float | None = None

    def open(self) -> None:
        """Open the breaker and cancel any in-progress overcurrent timing."""
        self.state = self.OPEN
        self._overcurrent_started_at = None

    def close(self) -> bool:
        """Close the breaker unless the trip latch is active."""
        if self.tripped:
            return False
        self.state = self.CLOSED
        return True

    def reset(self) -> None:
        """Clear the trip latch without changing the breaker position."""
        self.tripped = False
        self.trip_reason = None
        self._overcurrent_started_at = None

    def evaluate(
        self,
        *,
        current_percent: float | None,
        voltages_pu: Iterable[float | None],
        timestamp: float,
    ) -> dict[str, object]:
        """Evaluate one protection scan using a caller-supplied monotonic time."""
        now = float(timestamp)
        if not math.isfinite(now):
            raise ValueError("timestamp must be finite")

        self._evaluate_undervoltage(voltages_pu)
        self._evaluate_overcurrent(current_percent, now)
        return self.snapshot()

    def snapshot(self) -> dict[str, object]:
        """Return a JSON-serializable authoritative controller status."""
        return {
            "state": self.state,
            "tripped": self.tripped,
            "undervoltage_alarm": self.undervoltage_alarm,
            "trip_reason": self.trip_reason,
        }

    def _evaluate_overcurrent(
        self, current_percent: float | None, timestamp: float
    ) -> None:
        current = self._valid_measurement(current_percent)
        protection_enabled = self.state == self.CLOSED and not self.tripped

        if (
            not protection_enabled
            or current is None
            or current < self.pickup_percent
        ):
            self._overcurrent_started_at = None
            return

        if self._overcurrent_started_at is None:
            self._overcurrent_started_at = timestamp

        elapsed = timestamp - self._overcurrent_started_at
        delay_elapsed = elapsed >= self.trip_delay_s or math.isclose(
            elapsed,
            self.trip_delay_s,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
        if delay_elapsed:
            self.tripped = True
            self.trip_reason = "overcurrent"
            self.state = self.OPEN
            self._overcurrent_started_at = None

    def _evaluate_undervoltage(
        self, voltages_pu: Iterable[float | None]
    ) -> None:
        valid_voltages = [
            voltage
            for measurement in voltages_pu
            if (voltage := self._valid_measurement(measurement)) is not None
        ]
        if not valid_voltages:
            return

        if self.undervoltage_alarm:
            if all(
                voltage >= self.undervoltage_clear_pu
                for voltage in valid_voltages
            ):
                self.undervoltage_alarm = False
        elif any(
            voltage < self.undervoltage_assert_pu for voltage in valid_voltages
        ):
            self.undervoltage_alarm = True

    @staticmethod
    def _valid_measurement(value: float | None) -> float | None:
        if value is None:
            return None
        measurement = float(value)
        return measurement if math.isfinite(measurement) else None
