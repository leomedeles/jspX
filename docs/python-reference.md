# Python internals reference

## Ownership and control path

The Python implementation keeps physical modeling, control state, and
transport separate:

| Module | Owns | Does not own |
| --- | --- | --- |
| `src/power_grid.py` | Reference-feeder topology, source/load inputs, physical switch positions, power-flow solve, measurements | MQTT or trip-latch policy |
| `src/breaker_control.py` | One breaker's state, latch, definite-time current timer, voltage alarm | Pandapower, MQTT, Docker |
| `src/power_sim.py` | Control-scan orchestration, controller-to-plant writes, monotonic timing, queued MQTT events and publication | Electrical calculations |

```text
command or solved protection input
→ authoritative BreakerController
→ physical pandapower line switch
→ solved topology
→ telemetry and identified retained status
```

MQTT callbacks enqueue events. Only the control loop changes controller and
plant state.

## `ReferenceFeederGrid`

`ReferenceFeederGrid.build()` creates the fixed 110/20/0.4 kV radial feeder
documented in the README. Stored mappings make access identity-based:

| Mapping | Purpose |
| --- | --- |
| `bus_indices` | Canonical bus name to pandapower index |
| `line_indices` | `L1_FEEDER_HEAD` / `L2_FEEDER_TAIL` to line index |
| `transformer_indices` | `T1_PRIMARY` / `T2_SS1` to transformer index |
| `breaker_switch_indices` | `BRK_F1` / `BRK_R1` to physical line-switch index |
| `breaker_line_indices` | Breaker identity to its measured line |

Important public methods are:

| Method | Result |
| --- | --- |
| `set_scenario(name)` | Atomically accepts `NORMAL`, `TAIL_OVERCURRENT_TEST`, or `LOW_SOURCE_VOLTAGE` and applies source/load inputs |
| `set_breaker_closed(name, closed)` | Changes a physical switch by canonical breaker identity |
| `breaker_is_closed(name)` | Reads a physical switch by identity |
| `breaker_current_ka(name)` | Returns the largest finite solved terminal current for the breaker's line |
| `bus_voltage_pu(name)` | Returns one finite solved bus voltage or `None` |
| `solve(vary_load=False)` | Runs Newton–Raphson power flow and returns telemetry |
| `read_measurements()` | Returns JSON-safe bus, line, transformer, and source data |

Unknown bus or breaker identities raise `ValueError`. The fivefold test input
needs the configured 30-iteration solve limit. The aggregate is 50% constant
power / 50% constant current so that overload case has a converged solved
current.

Measurement conversion follows one rule set:

- non-finite values become `None` / JSON `null`;
- finite-voltage assets are energized and `GOOD`;
- unavailable assets are not energized and `NOT_ENERGIZED`;
- an open line switch makes through-current and line loading exactly zero;
- isolated transformer electrical values remain unavailable rather than being
  invented as zeros.

## `BreakerController`

The state machine is transport-independent:

```python
BreakerController(
    initial_state="CLOSED",
    pickup_ka=0.20,
    trip_delay_s=0.100,
    undervoltage_assert_pu=0.92,
    undervoltage_clear_pu=0.94,
)
```

`evaluate(current_ka, voltages_pu, timestamp)` uses a caller-supplied monotonic
timestamp. Current at or above pickup starts definite-time timing; a missing or
lower current resets unfinished timing. Once elapsed time reaches the delay,
the controller opens and latches `trip_reason="overcurrent"`.

`open()` always opens, `close()` rejects while latched, and `reset()` clears the
latch without changing the open position. Voltage alarm hysteresis is separate
from tripping: any valid input below 0.92 pu asserts, while all valid inputs at
or above 0.94 pu clear.

## `ControlledPandapowerSimulator`

The simulator creates these default controller settings:

| Identity | Current pickup | Delay | Voltage input |
| --- | ---: | ---: | --- |
| `BRK_F1` | 0.20 kA | 300 ms | `BUS_MV_SOURCE` |
| `BRK_R1` | 0.20 kA | 100 ms | none |

Each `control_step()`:

1. Applies both controller positions through the grid's generic breaker API.
2. Solves the plant.
3. Evaluates R1 and F1 from their solved line currents; F1 also evaluates the
   source-MV voltage.
4. If protection changed a position, applies the new position and solves again.
5. Returns telemetry for the resulting topology.

The second solve means a trip observation already contains the open-breaker
topology. In `TAIL_OVERCURRENT_TEST`, both timers initially see the solved
overload current. R1 reaches 100 ms first; after it opens, the next solved scan
removes tail current and resets F1's unfinished 300 ms timer.

## MQTT event and status path

`BreakerMqttEventQueue` subscribes only to the six canonical F1/R1 command
topics and `cmd/sim/scenario/set`. It translates messages into immutable
`BreakerMqttEvent` records; it never calls a controller.

`process_control_scan()` handles at most one queued event, runs the plant scan,
and returns `ControlScanResult`. The `statuses` mapping contains only identified
snapshots that are due because of startup, an addressed command, or a state
transition. `publish_breaker_status()` publishes those snapshots retained on
`status/breaker/BRK_F1` or `status/breaker/BRK_R1` with strict JSON.

Routine telemetry has no embedded breaker object. The retained identified
status is authoritative for operator state.

## Change routing

| Change | Primary source of truth |
| --- | --- |
| Physical asset, input, scenario, or measurement | `src/power_grid.py` |
| State, latch, reset, or protection rule | `src/breaker_control.py` |
| Scan order, MQTT routing, publication | `src/power_sim.py` |
| HMI and historian transform | `nodered/data/flows.json` |
| Operations visualization | `grafana/provisioning/` |
| Acceptance scope/evidence | `docs/BACKLOG.md` |
| Released behavior only | `CHANGELOG.md` |

Tests are the executable detail. This reference explains boundaries and should
remain smaller than the implementation.
