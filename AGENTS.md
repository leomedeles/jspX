# Repository guidance for coding agents

## Sources of truth

The README documents the current Rust reference-feeder laboratory and its
HTTP, data, and operating contracts. `docs/rust-reference.md` explains code
ownership and scan order. `docs/BACKLOG.md` holds acceptance criteria and live
evidence; `docs/DoD.md` is the shared completion standard. CHANGELOG describes
released behavior and the unreleased candidate separately. The `flows/`
directory contains historical Node-RED exports only.

Inspect branch, working tree, affected modules, and Compose configuration
before edits. Preserve unrelated work. Make requested changes on a working
branch. Do not merge, tag, publish, or create a PR without an explicit request.

## Architecture and control invariants

- `src/plant.rs` owns physical topology, source/load inputs, AC solving,
  physical breaker positions, and measurement quality.
- `src/control.rs` owns IED timing, latches, command acceptance, operation
  attempts at the plant boundary, post-scan feedback, and identified events.
- `src/main.rs` is the single writer of plant and control state. HTTP handlers
  only validate and enqueue intent. Keep 50 ms scans separate from 1 Hz
  electrical publication.
- `src/history.rs` stores snapshots and events. `src/api.rs` serves the current
  snapshot, history, SSE, and browser pages. The UI and historian observe the
  plant; neither enforces a control interlock by itself.
- Physical position, latch, events, solved topology, telemetry, and UI must
  agree after each scan, including refused operation. CLOSE is rejected while
  latched. RESET never moves a switch.
- Injected actuation failure belongs only at the plant operation boundary.
  Removing it does not clear latches or move switches. Tests must use a
  deterministic virtual monotonic clock.
- Emit strict JSON. Unavailable electrical values are `null` with energized
  and quality indicators. Do not fabricate voltage/current values or fill
  gaps. Open-switch topological zero is separate from measured current.

## Verification and hygiene

Run focused Rust tests and the full `cargo test` suite, format and lint checks,
and `docker compose config --quiet`. For cross-path changes, verify real
Compose/HTTP/SSE/history/UI behavior, not just container startup. Record
observations and gaps in the backlog. Do not mark a candidate complete while
a required check is missing.

Keep Docker ports bound to localhost; do not commit secrets or delete named
volumes as routine verification. Explain new dependencies. At handoff,
summarize changes, checks and results, limitations, and material architecture
decisions.
