# Rust internals reference

## Ownership and scan order

`plant.rs` owns source and load inputs, electrical branches, physical F1/R1
positions, connectivity, AC solving, and measurements. `control.rs` owns the
transport-independent IED state, timers, trip latch, request events, physical
operation attempts, and post-scan status. `history.rs` owns one embedded redb
database. `api.rs` only validates and queues HTTP intent, serves completed
snapshots and history, and streams published scan results. `main.rs` owns the
50 ms scheduling loop and the single `Simulator` writer.

One scan takes at most one queued intent, applies any operator request at the
plant boundary, solves the actual topology, evaluates both IEDs from solved
measurements and physical positions, attempts any protection OPEN, solves
again, and commits events plus any due snapshot. Only after historian commit
does it publish the new snapshot/events to SSE. Control scans continue between
1 Hz electrical samples. Status transitions are stored immediately. A `202`
HTTP response means that a command is queued; it is not an IED acceptance or
physical-operation result.

Protection uses monotonic milliseconds supplied by the scheduler (and by
tests), while history timestamps use UTC. Event IDs are a run UUID plus an
in-run sequence. Events share their completed scan timestamp and physical
position. The 100 ms R1 trip and 300 ms F1 backup are tested with a virtual
clock. The opening failure scenario affects only `Plant::attempt()` for R1
OPEN; it never changes an IED decision or invents position feedback.

## Electrical solve and quality

The fixed five-bus, balanced AC network uses a 100 MVA base. Branch admittances
are the frozen pandapower 3.1.2 T-model equivalents for T1/T2 and π-model
equivalents for L1/L2, including both 150° transformer phase shifts and 50 Hz
line charging. A small rectangular Newton solve with numerical Jacobian and
LU decomposition solves only buses connected to the source. The fivefold ZIP
load has two converged solutions; an explicit low-voltage seed selects the
pandapower reference branch. Frozen fixture tests compare all five defined
plant conditions within the README tolerances.

The plant, not the controller, owns breaker position. Unavailable bus, line,
and transformer voltage/current values are `null` with a quality state.
`NOT_ENERGIZED` means topology removes supply. `UNKNOWN` means the solve failed
or the browser's live snapshot is stale. An open switch gives a known
topological through-current of zero in `inferred_through_current_ka`; `i_ka`
remains `null`, so history never presents an unmodeled sensor value as a valid
measurement. Energized L1 can still carry small charging current after R1
opens. Power and loading use the post-scan solved topology.

## Persistence and restart

The application stores electrical snapshots at roughly 1 Hz, plus snapshots
when breaker status changes, and every IED/operation/scenario/run event at scan
resolution. Timestamp-first redb keys support ordered UTC range reads. A daily
prune removes records older than 30 days. A restart intentionally creates a
fresh NORMAL run with F1/R1 closed and clear latches; `RUN_STARTED` marks the
boundary. Engineering charts split on `run_id`, unavailable values, or an
electrical sampling gap over 1.5 seconds. Existing records remain until their
retention deadline. An unsuccessful historian commit ends the process rather
than broadcasting an unrecorded state; Docker restarts it as a new run.

## External surface

The stable endpoints and exact scenario names are in the README. JSON is
strict: no `NaN` or infinity is serialized. `/api/v1/stream` is a live aid,
not durable replay. The client re-reads `/api/v1/snapshot` after a stream lag
or reconnect, and queries `/api/v1/events` for past events. The feeder page is
the operational view. Panel pages have no command buttons. Engineering pages
query the same historian and contain no control function.
