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

## Sprint 3 (2 weeks) → v0.3.0: Historian + Grafana

**Goal:** Persist 1 Hz telemetry to a time-series DB (InfluxDB) and visualize it in Grafana.

### Scope (stories & tasks)
- [x] **Sim backend**
  - [x] Confirm JSON schema fits Influx line protocol (or transform).
  - [-] NOT NEEDED - Add `--influx` flag in `power_sim.py` to POST directly to Influx (optional).
- [x] **Node-RED flow**
  - [x] Write bus metrics into Influx (`measurement=grid`, tags: `{bus:name}`, fields: `{vm_pu,p_mw,q_mvar}`).
  - [x] Create a basic Grafana dashboard (voltages, P, Q).
- [x] **Docs & verification**
  - [x] Add README “Historian” section and Grafana screenshot.
  - [x] Optionally add `docker-compose.yml` with Node-RED + InfluxDB + Grafana.

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

# Project Backlog

This backlog is a living list of possible tasks, features, and improvements.  
Not everything here will be done — items can be added, removed, or reprioritized over time.  

---

## Near-term candidates
- [x] Add historian (InfluxDB) for telemetry storage (`v0.3.0`)
- [x] Build Grafana dashboard for voltages and power trends (`v0.3.0`)
- [x] Add `--influx` option in sim (direct or via Node-RED)

## Medium-term
- [ ] Add alerting logic (breaker trip if overcurrent, bus undervoltage)
- [ ] Package with Docker Compose (Node-RED + sim + DB + Grafana)
- [ ] Write SECURITY.md (list hygiene + mitigations)

## Longer-term / stretch
- [ ] Add AI anomaly detection module (IsolationForest/autoencoder)
- [ ] Integrate OPC UA or Modbus protocol simulation
- [ ] Build a short demo video/gif and embed in README
- [ ] Optional: add simple C++ component for protocol handling

---

## Done (closed items)
- [x] `v0.1.0`: Hello SCADA loop (random sim + Node-RED flow)
- [x] `v0.2.0`: 3-bus pandapower model, new JSON schema, Node-RED flow + dashboard