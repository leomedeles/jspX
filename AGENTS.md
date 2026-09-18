# AGENTS.md

## Purpose

jspX is a small learning project for two subjects in parallel:

1. Control and SCADA engineering for electrical-energy systems.
2. Practical software-development workflows using Codex in VS Code.

Prefer a small, understandable, end-to-end system over feature count or production-scale complexity. Code must remain explainable to the human project owner.

## Repository workflow

- `main` is the stable/released branch. Do not commit directly on it.
- Inspect the current branch and working tree before changing anything; do not assume a branch name.
- Do not create, move or delete tags, merge branches, open pull requests, or push commits unless the user explicitly requests it.
- Keep commits focused. Conventional Commit style is preferred.
- Do not rewrite published history.

## Read before changing code

Before each task, read:

- `README.md`
- The relevant section of `docs/BACKLOG.md`, especially the current sprint.
- `CHANGELOG.md` when release context or previously released behavior matters.
- the implementation and configuration files directly involved in the task.

Inspect the current branch, working-tree state and relevant existing behavior. Preserve unrelated user changes.

## Architecture and ownership

- `src/power_grid.py` owns the physical pandapower model, topology and measurements.
- `src/breaker_control.py` owns the testable breaker/protection state machine.
- `src/power_sim.py` owns orchestration, timing and MQTT transport.
- Only the authoritative control path may change breaker state, trip latching, reset behavior and command acceptance.
- Node-RED is the HMI and integration layer. It may provide operator feedback, but it must not be the only place enforcing an interlock.
- InfluxDB and Grafana observe the system; they do not control it.

Keep the controller and protection logic independent from MQTT so it can be tested without a broker, Docker or real-time sleeps.

## Control-system invariants

- Control actions must change the authoritative plant state and the resulting telemetry.
- CLOSE must be rejected while the trip latch is active.
- RESET must never cause an implicit close.
- Protection/control evaluation must run faster than the  SCADA publication rate. Keep these rates separate.
- Use a monotonic clock for elapsed protection time and an injectable clock or explicit timestamps in unit tests.
- Fault scenarios must be deterministic and reversible.
- Status transitions should be published immediately; routine telemetry may slower cadence.
- Avoid invalid JSON values such as `NaN`. Represent unavailable measurements as `null` and expose a simple energized/quality indication.
- Use one internal writer for controller state. Transport callbacks should enqueue commands rather than mutate the plant state concurrently.

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

Run the checks relevant to the change. Behavior changes require deterministic automated tests.

For Compose, MQTT, HMI, historian, or dashboard changes, run the relevant integration checks, normally including:

```text
python -m pytest -q
docker compose config
docker compose up -d --build
docker compose ps
```

Use the acceptance criteria in the relevant backlog item for end-to-end verification. Do not claim a command passed unless its result was observed. If a dependency is unavailable, report that verification as incomplete.

## Documentation discipline

Keep documentation small and authoritative:

- `README.md`: system purpose, architecture, operating instructions, and durable model scope/simplifications.
- `docs/BACKLOG.md`: current sprint scope, acceptance criteria, completion state, and short roadmap.
- `CHANGELOG.md`: released behavior.
- `SECURITY.md`: concise development-security limitations.
- `AGENTS.md`: stable instructions for Codex.

Do not duplicate current sprint scope, acceptance criteria, release status, or task-specific settings in `AGENTS.md`.

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
