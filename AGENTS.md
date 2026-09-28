# Repository guidance for coding agents

## Project and sources of truth

jspX simulates a radial distribution feeder with an operator-to-plant-to-historian control path. `README.md` describes the current system and how to operate it.

Use `docs/BACKLOG.md` for selected sprint scope, feature acceptance criteria, candidates, and recorded acceptance evidence. `docs/DoD.md` contains reusable completion criteria. `CHANGELOG.md` describes released behavior.

Read the documents relevant to the task. Do not treat historical sprint descriptions as current interfaces; check the implementation and README.

## Before changing anything

Inspect the branch, working tree, affected implementation, and relevant configuration. Preserve unrelated changes. Identify the affected control or data path before editing it.

`main` is the released branch; make requested changes on a working branch. Keep commits focused and do not rewrite published history. Leave the work on the branch until the user explicitly requests a pull request. Do not merge, create or move tags, or publish a release without an explicit request.

## Architecture and authoritative state

- `src/power_grid.py` owns physical topology, source/load inputs, power-flow solving, switch positions, and measurements.
- `src/breaker_control.py` owns control/protection state, interlocks, trip latching, protection timing, and alarms. Keep it independent of MQTT and Docker.
- `src/power_sim.py` owns scan orchestration, queued MQTT events, and controller-to-plant writes. Transport callbacks enqueue intent; they do not mutate controller or plant state.
- Node-RED is the HMI and historian integration layer. It must not be the sole enforcer of a control interlock.
- InfluxDB and Grafana observe the system; they do not control it.

The active Node-RED definition is `nodered/data/flows.json`; `flows/` contains historical exports. Grafana provisioning is under `grafana/provisioning/`. Compose topology is in `docker-compose.yml`, Python dependencies in `requirements.txt`, and MQTT configuration in `mqtt/config/mqtt.conf`. Do not create a second active flow or dashboard definition.

## Control invariants

- A breaker command or protection trip requests an operation; acceptance
  does not prove that the switch moved. The plant owns physical position.
  Post-scan position feedback, retained status, events, solved topology, and
  telemetry must agree about the actual result, including failed actuation.
- Reject CLOSE while the breaker is trip-latched. RESET clears the latch without closing the breaker.
- Use monotonic elapsed time for protection. Keep control scans separate from the slower telemetry publication rate.
- Make test scenarios deterministic and reversible. Injected actuation failures
  must be explicit test-harness conditions at the plant-operation boundary.
  They must not directly force an IED decision or fabricate position feedback;
  IEDs may respond to measurements produced by the altered plant state.
  Removing the injection does not reset latches or move switches.
- Emit strict JSON: unavailable electrical measurements are `null`, with energized and quality information. Never emit `NaN`.

## Verification and documentation

For behavior changes, add or update deterministic tests for the affected behavior and run the relevant checks. The Python suite is `python -m pytest -q`. For changes crossing Compose, MQTT, Node-RED, InfluxDB, or Grafana, verify the affected end-to-end path when the stack is available; relevant commands include `docker compose config --quiet`, `docker compose up -d --build`, and `docker compose ps`. Report what was observed and what could not be verified. Use the selected backlog item's acceptance criteria and applicable DoD conditions; do not mark completion from code changes alone.

Keep the README current for operation and interfaces, the backlog current for plans and evidence, and the changelog accurate for releases. Avoid duplicating those facts in this file or creating another planning document.

Do not commit credentials. Mark example values as development placeholders, keep development ports bound to localhost, and do not delete named volumes as routine verification. Explain why a new dependency is needed.

At handoff, summarize the change, checks and results, remaining limitations, and any control or architecture decision the user needs to understand.
