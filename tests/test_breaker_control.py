import json

from src.breaker_control import BreakerController


def evaluate(
    controller: BreakerController,
    current_ka: float | None,
    timestamp: float,
    voltages_pu: tuple[float | None, ...] = (1.0,),
) -> None:
    controller.evaluate(
        current_ka=current_ka,
        voltages_pu=voltages_pu,
        timestamp=timestamp,
    )


def trip_controller(controller: BreakerController) -> None:
    evaluate(controller, current_ka=0.20, timestamp=0.00)
    evaluate(controller, current_ka=0.20, timestamp=0.10)


def test_initial_state_and_snapshot_are_serializable() -> None:
    controller = BreakerController()

    assert controller.pickup_ka == 0.20
    assert controller.trip_delay_s == 0.100
    assert controller.undervoltage_assert_pu == 0.92
    assert controller.undervoltage_clear_pu == 0.94
    assert controller.snapshot() == {
        "state": "CLOSED",
        "tripped": False,
        "undervoltage_alarm": False,
        "trip_reason": None,
    }
    json.dumps(controller.snapshot(), allow_nan=False)


def test_manual_open_and_close() -> None:
    controller = BreakerController()

    controller.open()
    assert controller.state == "OPEN"
    assert controller.close() is True
    assert controller.state == "CLOSED"


def test_close_is_rejected_while_tripped() -> None:
    controller = BreakerController()
    trip_controller(controller)

    assert controller.close() is False
    assert controller.state == "OPEN"


def test_no_trip_below_pickup() -> None:
    controller = BreakerController()

    evaluate(controller, current_ka=0.199, timestamp=0.00)
    evaluate(controller, current_ka=0.199, timestamp=1.00)

    assert controller.tripped is False
    assert controller.state == "CLOSED"


def test_no_trip_before_100_ms() -> None:
    controller = BreakerController()

    evaluate(controller, current_ka=0.20, timestamp=0.00)
    evaluate(controller, current_ka=0.20, timestamp=0.05)
    evaluate(controller, current_ka=0.20, timestamp=0.099)

    assert controller.tripped is False
    assert controller.state == "CLOSED"


def test_trip_at_100_ms() -> None:
    controller = BreakerController()

    trip_controller(controller)

    assert controller.tripped is True
    assert controller.state == "OPEN"
    assert controller.trip_reason == "overcurrent"


def test_pickup_timer_resets_below_threshold() -> None:
    controller = BreakerController()

    evaluate(controller, current_ka=0.20, timestamp=0.00)
    evaluate(controller, current_ka=0.199, timestamp=0.05)
    evaluate(controller, current_ka=0.20, timestamp=0.10)
    evaluate(controller, current_ka=0.20, timestamp=0.19)

    assert controller.tripped is False

    evaluate(controller, current_ka=0.20, timestamp=0.20)
    assert controller.tripped is True


def test_trip_remains_latched_after_current_returns_to_normal() -> None:
    controller = BreakerController()
    trip_controller(controller)

    evaluate(controller, current_ka=0.05, timestamp=0.20)

    assert controller.tripped is True
    assert controller.state == "OPEN"
    assert controller.trip_reason == "overcurrent"


def test_reset_clears_latch_and_leaves_breaker_open() -> None:
    controller = BreakerController()
    trip_controller(controller)

    controller.reset()

    assert controller.tripped is False
    assert controller.trip_reason is None
    assert controller.state == "OPEN"


def test_close_succeeds_after_reset() -> None:
    controller = BreakerController()
    trip_controller(controller)

    controller.reset()

    assert controller.close() is True
    assert controller.state == "CLOSED"


def test_undervoltage_assertion_hysteresis_and_clearing() -> None:
    controller = BreakerController()

    evaluate(controller, 0.05, 0.00, (0.919,))
    assert controller.undervoltage_alarm is True

    evaluate(controller, 0.05, 0.05, (0.92,))
    evaluate(controller, 0.05, 0.10, (0.939,))
    assert controller.undervoltage_alarm is True

    evaluate(controller, 0.05, 0.15, (0.94,))
    assert controller.undervoltage_alarm is False


def test_missing_voltages_do_not_assert_or_clear_alarm_by_themselves() -> None:
    controller = BreakerController()

    evaluate(controller, 0.05, 0.00, (None, float("nan")))
    assert controller.undervoltage_alarm is False

    evaluate(controller, 0.05, 0.05, (0.91, None))
    assert controller.undervoltage_alarm is True

    evaluate(controller, 0.05, 0.10, (None, float("nan")))
    assert controller.undervoltage_alarm is True

    evaluate(controller, 0.05, 0.15, (None, 0.94))
    assert controller.undervoltage_alarm is False


def test_protection_settings_are_configurable() -> None:
    controller = BreakerController(
        pickup_ka=0.30,
        trip_delay_s=0.20,
        undervoltage_assert_pu=0.90,
        undervoltage_clear_pu=0.95,
    )

    evaluate(controller, 0.299, 0.00, (0.91,))
    assert controller.tripped is False
    assert controller.undervoltage_alarm is False

    evaluate(controller, 0.30, 0.10, (0.89,))
    evaluate(controller, 0.30, 0.29, (0.94,))
    assert controller.tripped is False
    assert controller.undervoltage_alarm is True

    evaluate(controller, 0.30, 0.30, (0.95,))
    assert controller.tripped is True
    assert controller.undervoltage_alarm is False
