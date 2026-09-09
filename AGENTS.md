# AGENTS.md

## Purpose

jspX is a small learning project for two subjects in parallel:

1. Control and SCADA engineering for electrical-energy systems.
2. Practical software-development workflows using Codex in VS Code.

Prefer a small, understandable, end-to-end system over feature count or production-scale complexity. Code must remain explainable to the human project owner.

## Repository workflow

- `main` is the stable/released branch.
- `v040` is the development branch for the current v0.4.0 sprint.
- Make v0.4.0 changes on `v040`. Do not commit directly to `main`.
- Do not create, move or delete tags, merge branches, open pull requests, or push commits unless the user explicitly requests it.
- Keep commits focused. Conventional Commit style is preferred.
- Do not rewrite published history.

## Read before changing code

Before each task, read:

- `README.md`
- `docs/BACKLOG.md`, especially the current sprint
- `CHANGELOG.md`
- the implementation and configuration files directly involved in the task

Inspect the current branch, working-tree state and relevant existing behavior. Preserve unrelated user changes.

## Current sprint: v0.4.0

The goal is to complete one demonstrable control-and-protection loop:

- containerized pandapower simulator;
- real breaker state coupled to the simulated network topology;
- MQTT commands for OPEN, CLOSE and RESET;
- authoritative breaker and protection status;
- latched overcurrent trip;
- undervoltage alarm with hysteresis;
- deterministic overcurrent and undervoltage scenarios;
- Node-RED operation and status display;
- InfluxDB history and Grafana operations panels;
- repeatable tests and end-to-end verification.

Do not expand the sprint into Kubernetes, new industrial protocols, AI anomaly detection, additional grid models, production authentication/TLS, or a large framework migration.

## Architecture and ownership

- `src/power_grid.py` owns the physical pandapower model, topology and measurements.
- `src/breaker_control.py` should own the testable breaker/protection state machine.
- `src/power_sim.py` owns orchestration, timing and MQTT transport.
- The simulator/controller is authoritative for breaker state, trip latching, reset behavior and command rejection.
- Node-RED is the HMI and integration layer. It may provide operator feedback, but it must not be the only place enforcing an interlock.
- InfluxDB and Grafana observe the system; they do not control it.
- `relay.py` is an unfinished prototype. Reuse useful logic, but do not add a separate relay service during v0.4.0 unless the user changes the architecture explicitly.

Keep the controller and protection logic independent from MQTT so it can be tested without a broker, Docker or real-time sleeps.

## Control-system invariants

- OPEN must operate a real pandapower switch and change electrical telemetry.
- CLOSE must be rejected while the trip latch is active.
- RESET clears the latch but must not automatically close the breaker.
- Overcurrent pickup is 120% of the configured nominal line current.
- Intentional trip delay is 100 ms unless the sprint specification is explicitly changed.
- Protection/control evaluation must run faster than the 1 Hz SCADA publication rate. Keep these rates separate.
- Use a monotonic clock for elapsed protection time and an injectable clock or explicit timestamps in unit tests.
- Undervoltage asserts below 0.92 pu and clears only at or above 0.94 pu.
- Fault scenarios must be deterministic and reversible.
- Status transitions should be published immediately; routine telemetry may remain at 1 Hz.
- Avoid invalid JSON values such as `NaN`. Represent unavailable measurements as `null` and expose a simple energized/quality indication.
- Use one internal writer for controller state. MQTT callbacks should enqueue commands rather than mutate the plant concurrently.

## Versioned sources of truth

- Compose topology: `docker-compose.yml`
- Python runtime: `requirements.txt` and `dockerfile`
- Active Node-RED definition: `nodered/data/flows.json`
- Grafana dashboards and datasource: `grafana/provisioning/`
- MQTT configuration: `mqtt/config/mqtt.conf`

Do not create a second active copy of a flow or dashboard. Files under `flows/` may be treated as historical exports; do not update them as an alternative source of truth.

## Implementation method

For each requested slice:

1. Explain the current behavior or defect briefly.
2. State the invariants affected.
3. Propose the smallest implementation and verification plan.
4. Implement only that slice.
5. Add or update deterministic tests for behavior changes.
6. Run the relevant checks.
7. Report evidence, remaining risks and what the user should understand from the change.

Do not mark backlog items complete solely because code was written. Completion requires test or manual verification evidence matching the acceptance criterion.

## Verification

Use the checks relevant to the change. The intended minimum v0.4.0 verification set is:

```text
python -m pytest -q
docker compose config
docker compose up -d --build
docker compose ps
```

Also inspect relevant service logs and run the v0.4.0 end-to-end smoke test once it exists. Do not claim a command passed unless it was actually executed and its result was observed. If Docker or another dependency is unavailable, report the unverified item explicitly.

End-to-end verification must cover:

- OPEN changes the physical simulation and line current becomes approximately zero.
- CLOSE restores the connected state when not tripped.
- Overcurrent trips within the specified delay tolerance and remains latched.
- CLOSE is rejected while tripped.
- RESET clears the latch without closing the breaker.
- Undervoltage asserts and clears at the specified thresholds.
- Node-RED, InfluxDB and Grafana receive the resulting state.

## Documentation discipline

Keep documentation small and authoritative:

- `README.md`: system purpose, architecture and operating instructions.
- `docs/BACKLOG.md`: current sprint contract and short roadmap.
- `CHANGELOG.md`: released behavior.
- `SECURITY.md`: concise development-security limitations.
- `AGENTS.md`: stable instructions for Codex.

Update documentation only when behavior, interfaces, operation or sprint status actually changes. Do not create extra plans, reports, prompt files or decision records unless the user requests them or the existing files cannot express an important durable decision.

## Security and safety

- Never commit real passwords, tokens or Node-RED credentials.
- Keep example credentials clearly marked as development placeholders.
- Keep published service ports bound to localhost unless the user explicitly requests otherwise.
- Do not delete named volumes or other persistent runtime data as part of routine verification.
- Do not perform destructive Git operations.
- Do not add dependencies without explaining why they are necessary.

## Required task handoff

Finish each implementation task with a concise summary containing:

- files changed;
- behavior implemented;
- commands run and results;
- anything not verified;
- remaining risks or next dependency;
- a short explanation of the relevant control-engineering and software-design concept;
- a proposed focused commit message.
