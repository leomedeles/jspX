# Python internals reference

## Ownership and control path

The Python implementation keeps physical modeling, control state, and
transport separate:

| Module | Owns | Does not own |
| --- | --- | --- |
| `src/power_grid.py` | Reference-feeder topology, source/load inputs, physical switch positions, power-flow solve, measurements | MQTT or trip-latch policy |
| `src/breaker_control.py` | One breaker's request state, latch, definite-time current timer, voltage alarm | Pandapower, MQTT, Docker |
| `src/ied.py` | Reusable IED measurement binding and explicit F1/R1 protection/event configurations | Plant writes, MQTT |
| `src/power_sim.py` | Control-scan orchestration, one-shot plant operation attempts, queued MQTT intent, event and status publication | Electrical calculations |

```text
command or solved protection input
→ IED/BreakerController accepted operation request
→ one plant-operation attempt
→ actual pandapower line-switch feedback and solved topology
→ retained physical status, scan event, and slower telemetry
```

MQTT callbacks enqueue events. Only the control loop changes controller and
plant state.

## `ReferenceFeederGrid`

`ReferenceFeederGrid.build()` creates the fixed 110/20/0.4 kV radial feeder
documented in the README. Stored mappings make access identity-based:

```text
GRID_110KV -- T1_PRIMARY -- BUS_MV_SOURCE -- BRK_F1 --
L1_FEEDER_HEAD -- BUS_R1_REMOTE -- BRK_R1 -- L2_FEEDER_TAIL --
BUS_SS1_MV -- T2_SS1 -- BUS_SS1_LV -- LOAD_SS1_AGGREGATE
```

`BRK_F1` is the line switch at the source end of `L1_FEEDER_HEAD`; `BRK_R1`
is the line switch at the source end of `L2_FEEDER_TAIL`. Opening F1 therefore
isolates the remote point and SS1, while opening R1 leaves the remote point
energized and isolates only SS1.

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
| `set_scenario(name)` | Applies one of the four named source/load/failure test conditions; returns `False` without changing inputs for another name |
| `set_breaker_closed(name, closed)` | Attempts a physical switch operation by canonical identity; the failure test refuses R1 OPEN here |
| `breaker_is_closed(name)` | Reads a physical switch by identity |
| `breaker_current_ka(name)` | Returns the largest finite solved terminal current for the breaker's line |
| `bus_voltage_pu(name)` | Returns one finite solved bus voltage or `None` |
| `solve(vary_load=False)` | Runs Newton–Raphson power flow and returns telemetry |
| `read_measurements()` | Returns JSON-safe bus, line, transformer, and source data |

Unknown bus or breaker identities raise `ValueError`. The fivefold test input
needs the configured 30-iteration solve limit. The aggregate is 50% constant
power / 50% constant current so that overload case has a converged solved
current.

`SCENARIO_INPUTS` defines `NORMAL`, `TAIL_OVERCURRENT_TEST`,
`R1_OPENING_FAILURE_TEST`, and `LOW_SOURCE_VOLTAGE` together. The failure
condition uses the same fivefold load as the tail test and refuses only R1
OPEN at `set_breaker_closed`. Returning to `NORMAL` removes that refusal but
does not operate a switch or clear any IED latch.

Measurement conversion follows one rule set:

- non-finite values become `None` / JSON `null`;
- finite-voltage assets are energized and `GOOD`;
- unavailable assets are not energized and `NOT_ENERGIZED`;
- an open line switch makes through-current and line loading exactly zero;
- isolated transformer electrical values remain unavailable rather than being
  invented as zeros.

The returned telemetry shape is deliberately small and stable:

```text
{
  "ts": ISO-8601 UTC timestamp,
  "buses": [{name, vm_pu, va_degree, p_mw, q_mvar, energized, quality, ...}],
  "lines": [{name, end, i_ka, loading_percent, energized, quality, ...}],
  "transformers": [{name, loading_percent, energized, quality, ...}],
  "ext_grid": {name, p_mw, q_mvar, ...}
}
```

`buses`, `lines`, and `transformers` use canonical names and pandapower
indices. A line has one record for each `from` and `to` terminal. This routine
telemetry intentionally does not contain a breaker-state object; physical
breaker state is published in retained named status after each control scan.

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

`evaluate(current_ka, voltages_pu, timestamp, position_closed)` uses a
caller-supplied monotonic timestamp and actual plant position. Current at or
above pickup starts definite-time timing; a missing or lower current cancels
unfinished timing. At the delay it emits `TRIP_REQUEST` and latches
`trip_reason="overcurrent"`. `state` is the requested position, not physical
feedback. The controller records pickup, timing start/cancel, and trip
transitions for the scan without depending on MQTT.

`open()` requests OPEN, `close()` rejects while latched, and `reset()` clears
the latch without requesting a position change. Voltage alarm hysteresis is
separate from tripping: any valid input below 0.92 pu asserts, while all valid
inputs at or above 0.94 pu clear.

## `SimulatedIED`

`src/ied.py` binds the same component to two explicit configurations:

| IED | Breaker/position | Solved current | Voltage observation | Overcurrent delay | Voltage action |
| --- | --- | --- | --- | ---: | --- |
| `IED_F1` | `BRK_F1` | `I_L1` through `BRK_F1` | `BUS_MV_SOURCE` | 300 ms | alarm |
| `IED_R1` | `BRK_R1` | `I_L2` through `BRK_R1` | `BUS_R1_REMOTE` | 100 ms | none |

Both use a 0.20 kA pickup. The configuration also gives the event source
identity. The IED samples current, voltage, and actual switch position from
the solved plant, then evaluates its transport-independent controller.

## `ControlledPandapowerSimulator`

Each `control_step()`:

1. Attempts pending operator operations once at the plant boundary.
2. Solves the actual topology and samples both configured IEDs.
3. Converts protection trip transitions into one-shot OPEN operations; attempts
   them at the same plant boundary and solves again.
4. Records actual switch feedback and returns post-scan telemetry and events.

The second solve means a successful trip observation already contains the open
topology. In `TAIL_OVERCURRENT_TEST`, R1 opens at 100 ms and F1's unfinished
timer cancels on the next scan after current disappears. In
`R1_OPENING_FAILURE_TEST`, R1's request is refused and remains physically
CLOSED. Solved current persists, so F1 requests OPEN at 300 ms. No controller
position is written repeatedly: removing the failure injection does not retry
R1 OPEN, reset a latch, or move a switch.

## MQTT event and status path

`BreakerMqttEventQueue` subscribes only to the six canonical F1/R1 command
topics and `cmd/sim/scenario/set`. It translates messages into immutable
`BreakerMqttEvent` records; it never calls a controller.

`process_control_scan()` handles at most one queued event, runs the plant scan,
and returns `ControlScanResult`. The `statuses` mapping contains only identified
snapshots that are due because of startup, an addressed command, or a control
or physical state transition. `publish_breaker_status()` publishes post-scan
physical position alongside IED latch/alarm state, retained on
`status/breaker/BRK_F1` or `status/breaker/BRK_R1` with strict JSON.

`ControlScanResult.command_accepted` is `False` when a latched breaker rejects
`CLOSE`; `scenario_accepted` is `False` for an unsupported scenario. In both
cases the following solve and telemetry still report the unchanged authoritative
plant state. A retained status payload contains `ts`, `breaker`, physical
`state`, `tripped`, `undervoltage_alarm`, and `trip_reason`. In the injected
failure case, `state="CLOSED"` and `tripped=true` are both correct.

`ControlScanResult.events` holds scan-resolution IED records. Each has a UTC
`ts`, unique `event_id`, configured `ied` identity, `breaker`, `event`,
`scan_monotonic_s`, physical `position`, and `tripped`. The event kinds are
`PICKUP`, `TIMING_STARTED`, `TIMING_CANCELLED`, `TRIP_REQUEST`,
`OPERATION_REQUEST`, `POSITION_FEEDBACK`, `RESET`, and `CLOSE_REJECTED`.
Operation records include `requested_state` and `cause`; feedback includes
`actual_state` and Boolean `success`. `publish_ied_event()` sends strict JSON
to non-retained `event/ied` on every control scan with events, independently
of 1 Hz telemetry. Node-RED's existing Influx write path persists these as
`ied_event` with identity and event tags and a millisecond timestamp. An
unsuccessful R1 OPEN has `requested_state="OPEN"`, `actual_state="CLOSED"`,
and `success=false`.

The complete command set is:

| Intent | Topic | Payload |
| --- | --- | --- |
| F1 operation | `cmd/breaker/BRK_F1/open`, `/close`, or `/reset` | ignored |
| R1 operation | `cmd/breaker/BRK_R1/open`, `/close`, or `/reset` | ignored |
| Scenario selection | `cmd/sim/scenario/set` | One exact scenario name |

Routine telemetry has no embedded breaker object. The retained identified
status is authoritative for operator state.

## Change routing

| Change | Primary source of truth |
| --- | --- |
| Physical asset, input, scenario, or measurement | `src/power_grid.py` |
| State, latch, reset, or protection rule | `src/breaker_control.py` |
| IED identity, measurement binding, or settings | `src/ied.py` |
| Scan order, MQTT routing, publication | `src/power_sim.py` |
| HMI and historian transform | `nodered/data/flows.json` |
| Operations visualization | `grafana/provisioning/` |
| Acceptance scope/evidence | `docs/BACKLOG.md` |
| Released behavior only | `CHANGELOG.md` |

Tests are the executable detail. This reference explains boundaries and should
remain smaller than the implementation.
