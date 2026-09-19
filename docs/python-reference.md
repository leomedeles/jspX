# Python internals reference

## Purpose

jspX is a compact virtual electrical-feeder operations lab.

The Python side has three responsibilities:

1. Model the electrical feeder and solve its power flow.
2. Make breaker and protection decisions.
3. Safely connect those decisions to MQTT, telemetry, and the SCADA stack.

The important rule is:

```text
Command or protection decision
→ authoritative breaker controller state
→ physical pandapower switch
→ solved electrical topology
→ telemetry and retained status
```

Node-RED, InfluxDB, and Grafana observe or request actions. They do not directly alter the electrical model.

## Module map

| Module                   | Responsibility                                                                                         | Must not own                        |
| ------------------------ | ------------------------------------------------------------------------------------------------------ | ----------------------------------- |
| `src/power_grid.py`      | Buses, lines, loads, physical switches, pandapower solve, measurements, deterministic scenarios        | MQTT, UI, trip-latch logic          |
| `src/breaker_control.py` | State of one breaker, trip latch, overcurrent timer, undervoltage alarm                                | Pandapower DataFrames, MQTT, Docker |
| `src/power_sim.py`       | Control-scan timing, controller-to-switch application, MQTT callbacks/queue, file and MQTT publication | Electrical calculations themselves  |
| `tests/`                 | Deterministic proof of electrical, protection, MQTT, and configuration behaviour                       | Runtime configuration ownership     |

## Electrical model: `power_grid.py`

### `ThreeBusGrid`

`ThreeBusGrid` is the simulated physical plant. It contains a real pandapower network and enough stored indices to identify the fixed teaching feeder.

```text
BUS0_SLACK → BRK_L1_SOURCE → L1 → BUS1_LOAD → BRK_L2 → L2 → BUS2_LOAD
```

It is intentionally a fixed three-bus feeder, not a reusable grid-builder framework.

### Stored state

| Attribute                  | Meaning                                                                             |
| -------------------------- | ----------------------------------------------------------------------------------- |
| `net`                      | The pandapower network, including buses, loads, lines, switches, and solved results |
| `base_p_mw`, `base_q_mvar` | Normal active/reactive demand for BUS1 and BUS2                                     |
| `protected_line_idx`       | L1’s pandapower line index; retained for v0.4 L1 protection behaviour               |
| `breaker_switch_idx`       | Physical switch index for `BRK_L1_SOURCE`                                           |
| `l2_line_idx`              | L2’s pandapower line index                                                          |
| `l2_breaker_switch_idx`    | Physical switch index for `BRK_L2`                                                  |
| `downstream_bus_indices`   | BUS1 and BUS2, used by the L1 protection path                                       |
| `scenario`                 | Active deterministic teaching condition                                             |
| `step_count`               | Counter used to make normal load variation repeatable                               |

### Scenarios

| Scenario                 | Physical result                                                                                                                                                           |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `NORMAL`                 | 1.0 pu source voltage and normal base demand                                                                                                                              |
| `OVERCURRENT`            | Five times normal downstream demand; L1 loading becomes high enough for the existing measurement-driven L1 overcurrent path                                               |
| `UNDERVOLTAGE`           | Source setpoint lowered to 0.90 pu; the existing undervoltage alarm can assert                                                                                            |
| `DOWNSTREAM_OVERCURRENT` | Does not create a calculated electrical fault. It is an explicit persistent teaching signal consumed by `power_sim.py` to demonstrate L2 primary and L1 backup protection |

### Construction and operating methods

| Method/property                     | Input                             | Output                                | Meaning                                                                         |
| ----------------------------------- | --------------------------------- | ------------------------------------- | ------------------------------------------------------------------------------- |
| `ThreeBusGrid.build(seed=42)`       | Optional NumPy seed               | New grid                              | Creates the three buses, two lines, two switches, loads, and starting state     |
| `set_scenario(scenario)`            | One valid scenario name           | `True` if accepted, otherwise `False` | Atomically applies source/load conditions and stores the selected scenario      |
| `breaker_closed`                    | None                              | Boolean                               | Physical position of `BRK_L1_SOURCE`                                            |
| `set_breaker_closed(closed)`        | Boolean                           | None                                  | Moves L1’s real pandapower switch                                               |
| `l2_breaker_closed`                 | None                              | Boolean                               | Physical position of `BRK_L2`                                                   |
| `set_l2_breaker_closed(closed)`     | Boolean                           | None                                  | Moves L2’s real pandapower switch                                               |
| `solve(vary_load=False)`            | Whether to apply normal variation | Telemetry dictionary                  | Runs pandapower Newton-Raphson power flow and returns JSON-safe measurements    |
| `step()`                            | None                              | Telemetry dictionary                  | Equivalent to `solve(vary_load=True)`                                           |
| `protected_line_loading_percent()`  | None                              | Finite number or `None`               | L1 loading used by the normal L1 protection path                                |
| `downstream_voltages_pu()`          | None                              | Tuple of finite values or `None`      | BUS1/BUS2 voltage inputs used by L1 undervoltage logic                          |
| `read_measurements()`               | None                              | Telemetry dictionary                  | Converts pandapower results into the public telemetry structure                 |
| `stream_jsonl(grid, hz, file_path)` | Grid, frequency, optional file    | Never returns normally                | Small local utility that repeatedly solves and prints/appends strict JSON lines |

### Measurement conversion

Pandapower may report `NaN` for a disconnected section. That is useful internally, but invalid in strict JSON and misleading to an operator.

`read_measurements()` therefore applies these rules:

* Any unavailable numeric value becomes `null`.
* A bus is energized only when it has a finite voltage.
* A line with an open switch is reported as:

  * `i_ka: 0.0`;
  * `loading_percent: 0.0`;
  * `energized: false`;
  * `quality: "NOT_ENERGIZED"`.
* A supplied item reports `quality: "GOOD"`.

The internal helpers `_json_number`, `_negated_json_number`, `_quality`, and `_line_switch_open` exist solely to keep those rules consistent.

## Breaker state machine: `breaker_control.py`

### `BreakerController`

`BreakerController` represents one breaker’s authoritative logical state. jspX creates one instance for L1 and one for L2.

It does not know where the physical switch is, which MQTT topic was used, or whether Docker is running. That separation makes it easy to unit-test.

### Constructor

```python
BreakerController(
    initial_state="CLOSED",
    pickup_percent=120.0,
    trip_delay_s=0.100,
    undervoltage_assert_pu=0.92,
    undervoltage_clear_pu=0.94,
)
```

| Parameter                | Meaning                                                             |
| ------------------------ | ------------------------------------------------------------------- |
| `initial_state`          | `OPEN` or `CLOSED`                                                  |
| `pickup_percent`         | Current percentage at which overcurrent timing starts               |
| `trip_delay_s`           | Definite-time delay before an asserted overcurrent trips            |
| `undervoltage_assert_pu` | Voltage threshold below which the alarm asserts                     |
| `undervoltage_clear_pu`  | Higher threshold at which the alarm clears; this creates hysteresis |

Invalid initial state, non-positive pickup, negative delay, or reversed voltage thresholds raise `ValueError`.

### State

| Field                     | Meaning                                                                             |
| ------------------------- | ----------------------------------------------------------------------------------- |
| `state`                   | `OPEN` or `CLOSED`                                                                  |
| `tripped`                 | Latching protection-trip state                                                      |
| `trip_reason`             | Current reason string, normally `"overcurrent"`, or `None`                          |
| `undervoltage_alarm`      | Alarm state; it is separate from the breaker trip latch                             |
| `_overcurrent_started_at` | Internal monotonic timestamp marking the beginning of a valid overcurrent condition |

### Public methods

| Method                                              | Behaviour                                                                                                 |
| --------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `open()`                                            | Opens the breaker immediately and cancels unfinished overcurrent timing                                   |
| `close()`                                           | Closes the breaker only if not latched as tripped; returns `True` when accepted and `False` when rejected |
| `reset()`                                           | Clears the trip latch and reason but deliberately does not close the breaker                              |
| `evaluate(current_percent, voltages_pu, timestamp)` | Executes one protection scan using caller-supplied monotonic time and returns a snapshot                  |
| `snapshot()`                                        | Returns JSON-safe state: `state`, `tripped`, `undervoltage_alarm`, and `trip_reason`                      |

### Protection behaviour

Overcurrent is a definite-time rule:

```text
current reaches pickup
→ remember start time
→ current remains at/above pickup for trip_delay_s
→ set tripped = true
→ set state = OPEN
```

If current disappears, becomes invalid, falls below pickup, or the breaker is already open/tripped, unfinished timing is cancelled.

Undervoltage is an alarm with hysteresis:

```text
any valid voltage < 0.92 pu
→ alarm on

all valid voltages ≥ 0.94 pu
→ alarm off
```

Undervoltage does not directly trip a breaker in the current model.

## Simulator and transport: `power_sim.py`

### Constants and topic maps

`power_sim.py` defines the 50 ms control period, breaker names, named MQTT topics, legacy L1 topics, and the fixed 150% teaching input for `DOWNSTREAM_OVERCURRENT`.

The named topics are built from these two identities:

```text
BRK_L1_SOURCE
BRK_L2
```

The legacy v0.4 topics still mean L1 only.

### `BreakerMqttEvent`

`BreakerMqttEvent` is a frozen record describing an incoming intent.

| Field              | Meaning                                     |
| ------------------ | ------------------------------------------- |
| `command`          | `OPEN`, `CLOSE`, or `RESET`, or `None`      |
| `breaker_name`     | Named target breaker, or `None`             |
| `status_requested` | Startup request to republish retained state |
| `scenario`         | Requested scenario string, or `None`        |

It contains no live MQTT object and cannot change the plant.

### `BreakerMqttEventQueue`

This class separates the asynchronous MQTT callback thread from the control loop.

| Method                                    | Behaviour                                                                                             |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `on_connect(client, userdata, flags, rc)` | On a successful connection, subscribes to command/scenario topics and queues a startup status request |
| `on_message(client, userdata, message)`   | Turns a recognised topic/payload into a `BreakerMqttEvent`; it does not operate a breaker             |
| `pop()`                                   | Returns one queued event or `None` without blocking                                                   |

This is the “single writer” rule in practice: callbacks ask; the control loop decides and applies.

### `ControlScanResult`

`process_control_scan()` returns this immutable record.

| Field                           | Meaning                                                        |
| ------------------------------- | -------------------------------------------------------------- |
| `telemetry`                     | Solved electrical snapshot                                     |
| `status`                        | Legacy L1 status for `status/breaker`, if due                  |
| `statuses`                      | Named authoritative statuses that should be published          |
| `command`, `breaker_name`       | Command handled in this scan                                   |
| `command_accepted`              | Whether the controller accepted it                             |
| `scenario`, `scenario_accepted` | Scenario handled in this scan and whether the grid accepted it |

### `ControlledPandapowerSimulator`

This is the central coordinator.

Its constructor receives:

* a `ThreeBusGrid`;
* an L1 `BreakerController`;
* optionally an L2 controller, otherwise it creates a normal one.

Internally it keeps:

* `controllers`: named controller mapping;
* `_physical_switch_setters`: named mapping from controller to the correct grid-switch setter;
* `controller`: L1 compatibility alias for older v0.4 code and legacy MQTT status.

### Core methods

| Method                                          | Behaviour                                                                                                                                             |
| ----------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `command_breaker(breaker_name, command)`        | Applies a command to the named controller only. Unknown breaker names raise `ValueError`. The physical switch remains unchanged until a control scan. |
| `_apply_controller_states()`                    | Writes each controller’s `OPEN`/`CLOSED` state to its matching physical pandapower switch.                                                            |
| `_evaluate_protection(timestamp)`               | Selects either the normal L1 measurement-driven path or the downstream teaching scenario.                                                             |
| `control_step(timestamp=None, vary_load=False)` | Runs one complete authoritative scan and returns solved telemetry.                                                                                    |

### One control scan

```text
1. Apply L1/L2 controller positions to physical switches.
2. Solve the grid.
3. Remember controller states.
4. Evaluate protection.
5. If a controller changed state, apply switches again and re-solve.
6. Attach legacy L1 breaker snapshot to telemetry.
```

This second solve matters: the telemetry published after a trip describes the new electrical topology, not the old one.

### Selective-protection teaching path

When the scenario is `DOWNSTREAM_OVERCURRENT`:

1. L2 receives a deterministic 150% current input.
2. After L2’s 100 ms delay, L2 trips and opens.
3. Only after L2 is tripped does L1 receive the same persistent teaching input.
4. If the scenario remains active for L1’s delay, L1 trips as backup.

This demonstrates the desired sequence, but it is not an electrical short-circuit calculation or real relay coordination study.

### Helper functions

| Function                                                       | Behaviour                                                                                                             |
| -------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `breaker_status_payload(controller, breaker_name=None)`        | Adds timestamp and, for named status, breaker identity to a controller snapshot                                       |
| `publish_breaker_status(client, status, breaker_name=None)`    | Serializes strict JSON and publishes retained legacy or named status                                                  |
| `apply_breaker_command(controller, command)`                   | Implements the `OPEN`, `CLOSE`, and `RESET` command vocabulary                                                        |
| `process_control_scan(simulator, event, timestamp, vary_load)` | Handles at most one queued event, runs the control scan, detects state changes, and calculates which statuses are due |
| `now_iso()`                                                    | Produces UTC ISO-8601 timestamps                                                                                      |
| `mqtt_defaults()`                                              | Reads MQTT host, port, publication topic, and rate from environment variables                                         |
| `run_controlled_loop(...)`                                     | Runs 20 Hz control scans with slower caller-provided telemetry publication                                            |
| `run_controlled_file_mode(...)`                                | Writes controlled pandapower telemetry to NDJSON                                                                      |
| `run_controlled_mqtt_mode(...)`                                | Runs the control loop with MQTT event intake, retained status, and telemetry publication                              |
| `run_file_mode(...)`, `run_mqtt_mode(...)`, `gen_sample(...)`  | Older random-telemetry mode retained for simple fallback behaviour                                                    |
| `main()`                                                       | Parses CLI arguments and chooses random or pandapower mode                                                            |

## Where a future change belongs

| Desired change                                         | First place to look                     |
| ------------------------------------------------------ | --------------------------------------- |
| Add a bus, line, load, switch, or physical measurement | `power_grid.py`                         |
| Change trip/reset/interlock rules                      | `breaker_control.py`                    |
| Add a new scenario-to-protection sequence              | `power_sim.py`, then tests              |
| Add MQTT topic or status routing                       | `power_sim.py`, README contracts, tests |
| Change operator controls or historian transformation   | `nodered/data/flows.json`               |
| Change dashboard panels                                | Grafana provisioning                    |
| Change acceptance scope                                | `docs/BACKLOG.md`                       |
| Describe released behaviour                            | `CHANGELOG.md`                          |

## Deliberate limits

* The feeder is fixed and radial.
* The downstream abnormal condition is scenario-driven.
* There are no CT/VT models, relay curves, directional elements, autoreclosing, breaker-failure logic, or fault location.
* The current code does not aim to be a reusable power-system protection framework.
* Tests are the executable proof of detailed behaviour; this document explains the design and boundaries rather than duplicating every assertion.
