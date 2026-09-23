## Sprint 6 → v0.6.0: Reference-feeder vertical migration (acceptance verified; release pending)

**Goal:** Replace the anonymous three-bus feeder with the v1 reference feeder while preserving a working operator-to-plant-to-historian SCADA loop.

### Scope

- [x] **Reference plant**
  - [x] Replace the 20 kV three-bus plant with the accepted radial chain: 110 kV upstream grid → T1 110/20 kV → 20 kV source bus → F1 → L1 → R1 → L2 → T2 20/0.4 kV → aggregate LV demand.
  - [x] Rename the grid model to reflect the reference feeder and create the canonical v1 asset names: `BRK_F1`, `BRK_R1`, `BUS_MV_SOURCE`, `BUS_R1_REMOTE`, and SS1 assets.
  - [x] Replace per-breaker plant setters with identity-based physical-breaker access.
  - [x] Publish bus, line, transformer, and topology/quality telemetry for the new plant.

- [x] **Protection semantics required by the new topology**
  - [x] Replace `OVERCURRENT` with `TAIL_OVERCURRENT_TEST`: fivefold demand behind T2 must produce solved tail current and give R1 the 100 ms primary trip opportunity.
  - [x] F1 remains a 300 ms upstream backup and remains closed after R1 clears the tail current.
  - [x] Replace `UNDERVOLTAGE` with `LOW_SOURCE_VOLTAGE`, with F1's existing undervoltage alarm observing the source MV bus.
  - [x] Remove the synthetic `DOWNSTREAM_OVERCURRENT` scenario; do not describe a scenario input as a calculated fault.

- [x] **Operational path**
  - [x] Migrate named MQTT commands and retained status to `BRK_F1` and `BRK_R1`; remove the unqualified L1 aliases and identity-less breaker telemetry object.
  - [x] Update the tracked Node-RED HMI, Influx mappings, and existing Grafana operations view so commands, authoritative status, and topology evidence use the canonical identities.
  - [x] Make transformer loading observable. No new scenario control is added to the HMI.

- [x] **Evidence and documentation**
  - [x] Add deterministic tests for normal supply, F1 isolation, R1 isolation, tail-overcurrent selectivity, MQTT command/status, and telemetry quality.
  - [x] Update README’s single-line diagram, MQTT contract, data mapping, operating walkthrough, and modeled/simplified/not-modeled boundary.
  - [x] Run the relevant Compose, MQTT, HMI, historian, and dashboard acceptance check. Record evidence before marking this sprint complete.

### Acceptance criteria

- [x] Normal operation supplies the aggregate LV demand through closed F1 and R1.
- [x] Opening F1 de-energizes the remote point and SS1; opening R1 leaves the remote point energized but de-energizes SS1.
- [x] `TAIL_OVERCURRENT_TEST` opens R1 first and leaves F1 closed once tail current disappears.
- [x] Node-RED OPEN/CLOSE/RESET, retained MQTT status, pandapower topology, InfluxDB, and Grafana agree for F1 and R1.
- [x] Transformer loading is visible and isolated values remain strict JSON `null` with the existing energized/quality meaning.
- [x] Automated tests, `docker compose config --quiet`, and recorded end-to-end stack verification pass.

### Acceptance evidence — 2026-09-23

- **Automated/configuration:** `.\.venv\Scripts\python.exe -m pytest -q` passed 53 tests; `docker compose config --quiet` passed.
- **Stack health:** `docker compose up -d --build` completed; `sim`, Node-RED, Mosquitto, InfluxDB, and Grafana were running, with `sim` and Node-RED healthy.
- **Normal and switching:** live MQTT telemetry showed closed F1/R1 supplying all reference-feeder buses; F1 OPEN de-energized the remote point and SS1; R1 OPEN kept `BUS_R1_REMOTE` energized and de-energized SS1.
- **Protection/recovery:** the first non-retained tail-test transition was the R1 overcurrent trip; retained status and topology showed R1 open/tripped, F1 closed/not tripped, and SS1 isolated. CLOSE was rejected while latched; RESET left R1 open; a later CLOSE restored SS1.
- **Voltage alarm:** `LOW_SOURCE_VOLTAGE` produced 0.896 pu at `BUS_MV_SOURCE`, asserted F1's alarm without a trip, and `NORMAL` cleared it.
- **HMI:** the live Node-RED dashboard was visually checked in normal operation and during the selective trip; it showed canonical F1/R1 identity, F1 closed/clear, R1 open/tripped, and `overcurrent` reason.
- **Historian/Grafana:** an Influx query returned canonical F1/R1 status plus T1/T2 loading and electrical fields. The provisioned v0.6 dashboard was fetched from Grafana, and its datasource query returned current loading frames for both transformers.
- **Retained migration:** three stale v0.5 retained messages in the reused broker volume were cleared individually; the retained wildcard then returned only `status/breaker/BRK_F1` and `status/breaker/BRK_R1`. No volume was deleted.
- **Release state:** acceptance is verified on the feature branch. Merge, tag, changelog release entry, and publication remain separate approval steps.

### Out-of-scope

- IED extraction/refactor from `power_sim.py`.
- `R1_OPENING_FAILURE_TEST`, `F1_ZONE_TEST`, calculated faults, and breaker-failure protection.
- CT/VT modelling, protection curves/coordination study, autoreclosing, RTU/gateway service, IEC 61850, extra feeders, ring supply, DER, or production-security work.

---

## Sprint 5 → v0.5.0: Selective feeder protection with BRK_L2 (released)

**Goal:** Demonstrate a second, downstream breaker as one complete operational slice: its physical feeder effect, protection decision, operator control, and historian/dashboard evidence agree.

### Scope

- [x] **Physical feeder**
  - [x] Add BRK_L2 as a real pandapower switch between BUS1 and L2.
  - [x] Opening BRK_L2 isolates BUS2 while BUS1 remains energized through BRK_L1_SOURCE.

- [x] **Selective protection and control**
  - [x] Extend the authoritative control path to manage the two breakers without transport callbacks directly mutating plant state.
  - [x] Model one deterministic downstream-overcurrent case in which BRK_L2 is the primary trip and BRK_L1_SOURCE remains available as delayed backup if the condition persists.

- [x] **Operator and observability path**
  - [x] Define and implement the per-breaker MQTT command/status contract.
  - [x] Extend the tracked Node-RED HMI for authoritative status and OPEN/CLOSE/RESET control of both breakers.
  - [x] Persist per-breaker status and show breaker/topology outcomes in Grafana.

- [x] **Documentation contracts and architecture**
  - [x] Replace the README raw flowchart text with a rendered Mermaid architecture diagram.
  - [x] Document telemetry, named breaker status, scenario commands, and InfluxDB measurement/tag/field mappings in README.
  - [x] Verify the documented contracts against the Compose/MQTT/Node-RED/Grafana acceptance run.

- [x] **Evidence**
  - [x] Add deterministic automated tests for topology, trip/reset interlocks, and the primary/backup scenario.
  - [x] Run the Compose/MQTT/HMI/Grafana end-to-end acceptance check and record the observed result.

### Acceptance criteria

- [x] A downstream-overcurrent scenario opens BRK_L2 first, keeps BUS1 energized, and isolates BUS2.
- [x] If the downstream condition remains uncleared, the modeled delayed backup behavior opens BRK_L1_SOURCE.
- [x] An operator can observe and command both breakers through Node-RED; telemetry, retained status, InfluxDB, and Grafana agree with the pandapower topology.
- [x] Automated tests and the end-to-end stack verification pass.

### Runtime acceptance evidence — 2026-09-20

- **Automated/configuration:** `python -m pytest -q` passed; `docker compose config --quiet` passed.
- **Stack health:** `docker compose up -d --build` started `sim`, Mosquitto, Node-RED, InfluxDB, and Grafana healthy.
- **Normal operation:** raw `telemetry/pandapower` contained strict JSON with BUS1/BUS2 energized and `loading_percent`; retained named L1/L2 statuses were `CLOSED` and not tripped.
- **Operator path:** MQTT and Node-RED OPEN/CLOSE of BRK_L2 changed the solved feeder topology; Node-RED and Grafana displayed the resulting status/topology.
- **Selective protection:** `DOWNSTREAM_OVERCURRENT` tripped BRK_L2 first, then BRK_L1_SOURCE as delayed backup while the scenario persisted.
- **Interlock and recovery:** CLOSE was rejected while trip-latched; RESET cleared each latch without closing; staged L1 then L2 CLOSE restored BUS1 and BUS2.
- **Result:** MQTT status, pandapower topology, Node-RED, InfluxDB-backed Grafana, automated tests, and Compose configuration agreed with the Sprint 5 acceptance criteria.

### Reality boundary

- **Modeled:** deterministic two-breaker primary/backup behavior and the resulting feeder topology.
- **Simplified:** protection inputs and operating conditions are scenario-driven rather than calculated electrical faults.
- **Not modeled yet:** CT/VT behavior, protection curves/settings coordination studies, directional elements, breaker-failure protection, autoreclosing, and fault location.

### Out-of-scope

- Grafana notification routing, new industrial protocols, AI anomaly detection, DER/BESS models, production authentication/TLS, and large framework changes.

---

## Sprint 4 → v0.4.0: Sim container + breaker control + basic protection

**Goal:** Demonstrate one complete, understandable control-and-protection loop: an operator command or protection decision changes a real simulated feeder, and the resulting state is visible through the SCADA stack.

**Sprint dashboard legend**

- [x] complete with durable evidence already recorded in the repository.
- [-] implemented and covered by committed automated-test code; final local/stack verification is still required.
- [ ] not yet implemented or not yet integrated.

### Implemented backend slices — final stack verification pending

- [x] **Containerize the simulator**
  - [x] Dockerfile (python:slim), non-root user, healthcheck.
  - [x] Env-driven config and sim service in Docker Compose.

- [x] **Physical breaker and electrically honest telemetry**
  - [x] Real source-side pandapower circuit breaker BRK_L1_SOURCE protects L1.
  - [x] Opening it isolates BUS1/BUS2; protected-line current/loading become zero.
  - [x] Unavailable isolated-bus values are strict JSON null, with energized and quality indicators.
  - [x] Control/protection scans run at 20 Hz while routine telemetry remains at the configured SCADA rate.

- [x] **Basic protection**
  - [x] L1 overcurrent pickup at 120% with a 100 ms definite-time delay; trip is latched.
  - [x] Bus undervoltage alarm asserts below 0.92 pu and clears at or above 0.94 pu.
  - [x] RESET clears the latch without closing; CLOSE is rejected while tripped.

- [x] **Simulator MQTT contract**
  - [x] OPEN: cmd/breaker/open
  - [x] CLOSE: cmd/breaker/close
  - [x] RESET: cmd/breaker/reset
  - [x] Authoritative retained status: status/breaker
  - [x] MQTT callbacks queue commands; the control loop is the single writer of controller/grid state.

- [x] **Current interface documentation**
  - [x] README documents the physical breaker and MQTT topic contract.
  - [x] CHANGELOG records the unreleased backend changes.

### Remaining v0.4.0 work

- [x] **Node-RED operation and status**
  - [x] Update the tracked active flow to publish OPEN/CLOSE/RESET on the current three-command topic contract.
  - [x] Subscribe to retained status/breaker and render authoritative position, trip state, and command rejection without a status-to-command feedback loop.
  - [x] Confirm the old combined cmd/breaker/main/set / status/breaker/main controls are removed or no longer active.

- [x] **Deterministic validation scenarios**
  - [x] cmd/sim/scenario/set accepts NORMAL, OVERCURRENT, and UNDERVOLTAGE.
  - [x] Scenarios provide repeatable evidence for trip timing, latching/reset, and UV hysteresis.

- [x] **Historian and Grafana Ops view**
  - [x] Store the authoritative breaker status and relevant alarms in InfluxDB.
  - [x] Add Grafana panels for breaker state and alarm/trip indication.

- [x] **Release verification and hygiene**
  - [x] Run and record python -m pytest -q.
  - [x] Run and record docker compose config, docker compose up -d --build, service status/log checks, and the end-to-end MQTT control smoke test.
  - [x] Add a minimal GitHub Actions workflow that runs the test suite before v0.4.0 release.
  - [x] Add concise SECURITY.md development-credentials/exposed-ports guidance.
  - [x] Update release notes, merge v040 into main, and create the v0.4.0 tag only after the acceptance criteria are verified.

### v0.4.0 acceptance criteria

- [x] Node-RED OPEN/CLOSE/RESET operates the real pandapower breaker; retained status appears promptly and never contradicts the physical topology.
- [x] The OVERCURRENT scenario trips within the specified timing tolerance, remains latched, rejects CLOSE, and requires RESET before a later CLOSE.
- [x] The UNDERVOLTAGE scenario asserts below 0.92 pu and clears only at or above 0.94 pu.
- [x] InfluxDB/Grafana show the resulting breaker state and alarms.
- [x] Automated tests and the Docker/MQTT end-to-end smoke test have recorded passing evidence.
- [x] CI is green for the final v0.4.0 candidate.

### Out-of-scope

- Production TLS/authentication and richer alert routing.
- Kubernetes, new industrial protocols, AI anomaly detection, additional grid models, and large framework changes.

---

## Sprint 3 (2 weeks) → v0.3.0: Historian + Grafana

**Goal:** Persist 1 Hz telemetry to a time-series DB (InfluxDB) and visualize it in Grafana.

### Scope (stories & tasks)
- [x] **Sim backend**
  - [x] Confirm JSON schema fits Influx line protocol (or transform).
  - [-] NOT NEEDED - Add `--influx` flag in `power_sim.py` to POST directly to Influx (optional).
- [x] **Node-RED flow**
  - [x] Write bus metrics into Influx (`measurement=grid`, tags: `{bus:name}`, fields: `{vm_pu,p_mw,q_mvar}`).
  - [x] Create a basic Grafana dashboard (voltages, P, Q).
- [x] **Containerization**
  - [x] Create Grafana container with datasource and panels provisioning
  - [x] Create InfluxDB container initialized with admin token
  - [x] Creat mqtt broker container with config file
  - [x] Create Node-RED container
- [x] **Docs & verification**
  - [x] Add README “Historian” section and Grafana screenshot.


### Acceptance criteria
- [x] At least 5 minutes of telemetry stored in Influx without errors.
- [x] Grafana dashboard shows live-updating voltages and powers.
- [x] README updated with screenshot + run instructions.
- [x] Tag `v0.3.0` with CHANGELOG entry.

### Out-of-scope
- Alerts
- AI anomaly detection
- OPC UA / Modbus

---

## Sprint 2 (2 weeks) → v0.2.0: Realistic grid via pandapower

**Goal:** Replace random telemetry with a tiny pandapower 3-bus system that emits realistic SCADA-like values every 1 s (file or MQTT), visible in Node-RED.

### Scope (stories & tasks)
- [x] Sim backend
  - [x] `pip install pandapower`
  - [x] Add `src/power_grid.py` that builds a 3-bus net:
        Bus1 ext_grid (slack), line to Bus2 (load), optional Bus3 (second load or PV)
  - [x] In a loop: vary loads slightly (±10%), `pp.runpp(net)`, extract per-bus `vm_pu`, `p_kw`, `q_kvar`
  - [x] Emit JSON lines; extend schema (e.g., `line_mw`, `backend: "pandapower"`)
  - [x] Integrate with `power_sim.py` via `--pandapower` flag (fallback to random if not set)
  - [x] Added pandapower and numpy to requirements.txt

- [x] Node-RED flow
  - [x] Update flow to accept new schema (file tail and MQTT paths)
  - [x] Keep Debug node; **optional** Dashboard if time allows
  - [x] Save updated flow to `flows/pandapower_3bus_flow.json`

- [x] Docs & verification
  - [x] Add ASCII diagram of the 3-bus system to README
  - [x] Screenshot Debug (and Dashboard if used) → `/docs`
  - [x] Update README “Verification” with new screenshot link

### Acceptance criteria
- [x] `python src/power_sim.py --pandapower` runs and outputs 1 line/s
- [x] Node-RED shows parsed values changing each second
- [x] No errors in Node-RED Debug for at least 60 s of runtime
- [x] README and flow JSON updated; screenshot present
- [x] Tag `v0.2.0` with CHANGELOG entry

---

# Project Backlog

This backlog is a living list of possible capabilities and improvements. Not every candidate will be implemented.

---

## Candidate queue

Priorities rank work after the active sprint. P1 is the next candidate to consider at sprint planning; it is not committed work until selected into a sprint.

- **P1 — Grafana alerts, annotations, and routing for breaker trips/alarms.** Revisit after the two-breaker operational slice provides meaningful events to alert on.
- **P2 — OPC UA or Modbus protocol simulation.** Select one protocol and define a small, explicit signal contract.
- **P3 — Short demo video or GIF embedded in the README.** Produce after the two-breaker operational story is stable.

## Parked

- **AI anomaly detection.** Revisit only after the simulator has credible event history and multiple operating scenarios.
- **Node-RED migration to a PLC environment.** Revisit after defining the learning objective and target PLC/runtime; it is an architecture decision, not a small replacement task.
- **Optional C++ protocol component.** Revisit only if a concrete protocol or performance need justifies it.

## Needs definition

- **“Hygene CMD/command: between compose and dockerfile”.** Retained from the prior backlog; define the actual command/configuration problem before ranking it.

---

## Closed releases
- [x] `v0.1.0`: Hello SCADA loop (random sim + Node-RED flow)
- [x] `v0.2.0`: 3-bus pandapower model, new JSON schema, Node-RED flow + dashboard
- [x] `v0.3.0`: extended JSON schema, Historian + UI, Contenarized environment: [mosquito, Node-RED, InfluxDB, Grafana]
- [x] `v0.3.1`: reproducible clone-to-dashboard startup path and runtime-state recovery.
- [x] `v0.4.0`: physical L1 breaker control/protection loop, Node-RED operation, historian, and Grafana evidence.
- [x] `v0.5.0`: two-breaker selective feeder protection with BRK_L2 primary and BRK_L1_SOURCE delayed backup, named MQTT control/status, Node-RED and Grafana observability, and documented acceptance evidence.

