## Sprint 4  → v0.4.0: Sim container + breaker control + basic protection

**Goal:** Close the one-command loop by containerizing the simulator and add a minimal control/protection path visible in Grafana.

### Scope (stories & tasks)
- [ ] **Containerize the simulator**
  - [ ] Dockerfile (python:slim), non-root user, healthcheck.
  - [ ] Env-driven config: BROKER_URL, PUB_TOPIC=telemetry/*, CMD_TOPIC=cmd/breaker/main/set,
        STATUS_TOPIC=status/breaker/main, RATE_HZ.
  - [ ] Add `sim` service to docker-compose with `.env` wiring.

- [ ] **Breaker control path**
  - [ ] Node-RED Dashboard toggle → publish OPEN/CLOSE to `cmd/breaker/main/set`.
  - [ ] Sim subscribes, updates breaker state, publishes `status/breaker/main` (OPEN/CLOSED, tripped boolean).
  - [ ] Telemetry reflects effect (e.g., line current → ~0 when open).

- [ ] **Basic protection**
  - [ ] Overcurrent trip on target line at 1.20 × nominal current with 50–200 ms intentional delay (latched).
  - [ ] Bus undervoltage alarm if Vm < 0.92 pu; clears when Vm ≥ 0.94 pu (hysteresis).
  - [ ] Manual reset: `cmd/breaker/main/reset` clears trip latch; CLOSE ignored while `tripped=true`.

- [ ] **Grafana “Ops”**
  - [ ] Panels for breaker state + alarm banner; optional annotations on trip events.

- [ ] **Docs & hygiene**
  - [ ] README: control topics, one-command note (no local Python needed for normal use).
  - [ ] CHANGELOG: add v0.4.0.
  - [ ] SECURITY (stub): dev creds policy, exposed ports, note future TLS/auth hardening.

### Acceptance criteria
- [ ] `docker compose up -d` starts sim + Node-RED + InfluxDB + Grafana; stack usable with no local Python.
- [ ] Toggling the Node-RED switch opens/closes the breaker; Grafana reflects within ~2 s.
- [ ] Overcurrent ⇒ tripped=true (latched); undervoltage ⇒ alarm; manual reset clears trip and enables CLOSE.
- [ ] Backlog updated; tag v0.4.0 recorded in CHANGELOG.

### Out-of-scope
- TLS/auth beyond the stub; richer alert routing and CI.

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
- [ ] Optional: add simple C++ component for protocol handling

---

## Done (closed items)
- [x] `v0.1.0`: Hello SCADA loop (random sim + Node-RED flow)
- [x] `v0.2.0`: 3-bus pandapower model, new JSON schema, Node-RED flow + dashboard
- [x] `v0.3.0`: extended JSON schema, Historian + UI, Contenarized environment: [mosquito, Node-RED, InfluxDB, Grafana]