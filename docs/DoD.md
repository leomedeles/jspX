# Definition of Done

A candidate is complete when its acceptance criteria have been demonstrated
against the running system and the evidence is recorded in `docs/BACKLOG.md`.
Code or container startup alone is not acceptance.

- Deterministic Rust tests cover affected plant, interlock, scan timing,
  feedback, quality, API, and history behavior. `cargo fmt --all -- --check`,
  `cargo clippy --all-targets -- -D warnings`, and `cargo test` pass.
- `docker compose config --quiet` and a clean build pass. The running Compose
  service becomes healthy, and actual command, feedback, snapshot, event,
  history, and browser paths are observed for affected behavior.
- Physical breaker position, protection latch, events, solved topology,
  telemetry, and operator indications agree, including failed actuation.
  Unavailable electrical values remain strict JSON `null` and chart gaps.
- README, Rust internals reference, backlog evidence, repository guidance,
  security guidance, and proposed release notes match the implemented system.
- Development ports remain localhost-only. Credentials are not committed.
  Existing named volumes are not deleted as routine verification.
- Required checks that could not be run are recorded as gaps. A release
  candidate remains open until those checks are observed. PR, merge, tag,
  and publication require a separate explicit decision.
