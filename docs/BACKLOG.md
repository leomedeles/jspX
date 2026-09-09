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

- [ ] **Release verification and hygiene**
  - [x] Run and record python -m pytest -q.
  - [x] Run and record docker compose config, docker compose up -d --build, service status/log checks, and the end-to-end MQTT control smoke test.
  - [x] Add a minimal GitHub Actions workflow that runs the test suite before v0.4.0 release.
  - [x] Add concise SECURITY.md development-credentials/exposed-ports guidance.
  - [ ] Update release notes, merge v040 into main, and create the v0.4.0 tag only after the acceptance criteria are verified.

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

This backlog is a living list of possible tasks, features, and improvements.  
Not everything here will be done — items can be added, removed, or reprioritized over time.  

---

## Near-term candidates
- [ ] Add alerting logic (breaker trip if overcurrent, bus undervoltage)
- [ ] Write SECURITY.md (list hygiene + mitigations)
- [ ] Hygene CMD/command: between compose and dockerfile

## Medium-term
- [ ] Grafana alerts/annotations & routing for trips/alarms (post-S4 refinement)

## Longer-term / stretch
- [ ] Add AI anomaly detection module (IsolationForest/autoencoder)
- [ ] Integrate OPC UA or Modbus protocol simulation
- [ ] Build a short demo video/gif and embed in README
- [ ] Migrate Node-RED to a PLC environment
- [ ] Increase Complexity/particularity of Simulation
- [ ] Optional: add simple C++ component for protocol handling

---

## Done (closed items)
- [x] `v0.1.0`: Hello SCADA loop (random sim + Node-RED flow)
- [x] `v0.2.0`: 3-bus pandapower model, new JSON schema, Node-RED flow + dashboard
- [x] `v0.3.0`: extended JSON schema, Historian + UI, Contenarized environment: [mosquito, Node-RED, InfluxDB, Grafana]
