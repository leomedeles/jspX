## Sprint 2 (2 weeks) → v0.2.0: Realistic grid via pandapower

**Goal:** Replace random telemetry with a tiny pandapower 3-bus system that emits realistic SCADA-like values every 1 s (file or MQTT), visible in Node-RED.

### Scope (stories & tasks)
- [ ] Sim backend
  - [ ] `pip install pandapower`
  - [ ] Add `src/power_grid.py` that builds a 3-bus net:
        Bus1 ext_grid (slack), line to Bus2 (load), optional Bus3 (second load or PV)
  - [ ] In a loop: vary loads slightly (±10%), `pp.runpp(net)`, extract per-bus `vm_pu`, `p_kw`, `q_kvar`
  - [ ] Emit JSON lines; extend schema (e.g., `line_mw`, `backend: "pandapower"`)
  - [ ] Integrate with `power_sim.py` via `--pandapower` flag (fallback to random if not set)

- [ ] Node-RED flow
  - [ ] Update flow to accept new schema (file tail and MQTT paths)
  - [ ] Keep Debug node; **optional** Dashboard if time allows
  - [ ] Save updated flow to `flows/hello_scada_flow.json`

- [ ] Docs & verification
  - [ ] Add ASCII diagram of the 3-bus system to README
  - [ ] Screenshot Debug (and Dashboard if used) → `/docs`
  - [ ] Update README “Verification” with new screenshot link

### Acceptance criteria
- [ ] `python src/power_sim.py --pandapower` runs and outputs 1 line/s
- [ ] Node-RED shows parsed values changing each second
- [ ] No errors in Node-RED Debug for at least 60 s of runtime
- [ ] README and flow JSON updated; screenshot present
- [ ] Tag `v0.2.0` with CHANGELOG entry

### Out-of-scope (keep it lean)
- InfluxDB/Grafana
- Docker/Compose
- Alerts/controls

### Risks & fallbacks
- If pandapower install is slow → commit `power_grid.py` stub that returns fixed values; switch to real `pp.runpp` before tagging.
- If Dashboard node install lags → rely on Debug; add Dashboard next sprint.

### Timebox
- Est. 6–8 focused hours total; aim for two 3–4 h sessions.



# Project Backlog

This backlog is a living list of possible tasks, features, and improvements.  
Not everything here will be done — items can be added, removed, or reprioritized over time.  
Each sprint we pick a subset to focus on.

---

## Near-term candidates
- [ ] Add **pandapower** 3-bus grid sim and emit voltages/powers (`v0.2.0`)
- [ ] Update Node-RED flow to parse new telemetry schema
- [ ] Add ASCII diagram of grid to README
- [ ] Store verification screenshots in `/docs`

## Medium-term
- [ ] Add historian (InfluxDB) for telemetry storage
- [ ] Build Grafana dashboard for voltages and power trends
- [ ] Add alerting logic (e.g. trip breaker if overcurrent)
- [ ] Package with Docker Compose (Node-RED + sim + DB)
- [ ] Write SECURITY.md (list hygiene + mitigations)

## Longer-term / stretch
- [ ] Add AI anomaly detection module (IsolationForest/autoencoder)
- [ ] Integrate OPC UA or Modbus protocol simulation
- [ ] Build a short demo video/gif and embed in README
- [ ] Optional: add simple C++ component for protocol handling

---

## Done (closed items)
- [x] `v0.1.0`: Hello SCADA loop (random sim + Node-RED flow)
