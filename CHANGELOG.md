
# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — Rust v1 release candidate

### Added

- One Rust and Docker reference-feeder laboratory with a balanced AC solve,
  F1/R1 IEDs, queued HTTP commands, physical feedback, and SSE live state.
- A feeder single-line, read-only F1/R1 panel portrayals, and an engineering
  review with voltage bases, separated actual-voltage views, electrical and
  energization trends, and scan-resolution event history.
- A 30-day embedded historian with distinct inferred open-switch zero and
  unavailable current, explicit run boundaries, and strict JSON quality.

### Changed

- Replaced the Python, Node-RED, Mosquitto, InfluxDB, and Grafana runtimes on
  this branch. The Rust v1 uses HTTP/SSE rather than MQTT topics. Historical
  `flows/` exports remain unexecuted.
- A restart begins a new NORMAL run with closed switches and clear latches;
  earlier history remains until its retention deadline.

This entry is proposed release content. No v1 version, tag, or publication has
been assigned.

## [0.6.0] - 2026-09-26

### Added

- Added the 110/20/0.4 kV reference radial feeder: upstream grid, T1, F1,
  L1, remote R1, L2, T2, and aggregate LV demand.
- Added canonical F1/R1 MQTT commands and retained authoritative breaker status.
- Added transformer telemetry/loading and reference-feeder topology/quality
  measurements through Node-RED, InfluxDB, and Grafana.
- Added deterministic `TAIL_OVERCURRENT_TEST` and `LOW_SOURCE_VOLTAGE`
  scenarios for the reference feeder.

### Changed

- Replaced the v0.5 three-bus feeder identities and MQTT aliases with the
  canonical reference-feeder contract.
- Corrected selective protection semantics: R1 is the 100 ms primary device
  for tail overcurrent, while F1 remains the 300 ms upstream backup.

### Fixed

- Grafana bus-voltage trends now show a visible gap while SS1 is de-energized,
  rather than visually connecting values across the isolation interval.

## [0.5.0] - 2026-09-20

### Added

* Added BRK_L2 as a real downstream pandapower switch, allowing BUS2 to be isolated while BUS1 remains energized through BRK_L1_SOURCE.
* Added named per-breaker MQTT OPEN, CLOSE, and RESET commands with retained authoritative status for BRK_L1_SOURCE and BRK_L2.
* Added the deterministic `DOWNSTREAM_OVERCURRENT` scenario: BRK_L2 trips as the primary breaker, while BRK_L1_SOURCE acts as delayed backup if the condition persists.
* Added two-breaker Node-RED operation, InfluxDB status persistence, and Grafana visibility for breaker and topology outcomes.
* Added deterministic topology, command/interlock, and selective-protection tests.
* Added durable MQTT, telemetry, historian, architecture, and Python-reference documentation.

### Changed

* Preserved the v0.4 L1 MQTT command/status aliases and the legacy L1-only `breaker` telemetry snapshot for compatibility.

### Fixed

* Preserved line `loading_percent` telemetry through the Node-RED historian transform.

## [0.4.0] - 2026-09-09

### Added

- Added a real source-side pandapower circuit breaker on the protected L1
  feeder path and connected it to the existing breaker/protection controller.
- Added strict-JSON measurement quality and energized indicators for topology
  states where downstream electrical results are unavailable.
- Added payload-independent MQTT commands on `cmd/breaker/open`,
  `cmd/breaker/close`, and `cmd/breaker/reset`, with authoritative retained
  strict-JSON status on `status/breaker`.
- Added deterministic `NORMAL`, `OVERCURRENT`, and `UNDERVOLTAGE` plant
  scenarios on `cmd/sim/scenario/set` for protection validation.
- Added InfluxDB persistence for authoritative breaker/protection status and a
  compact Grafana Operations view for current state, alarms, and recent history.

### Changed

- Pandapower mode now evaluates controller protection at 20 Hz using L1's
  solved loading while keeping telemetry publication on its configured cadence.
- Grafana Operations stat panels now retain the timestamp/value frame and
  reduce explicitly on the `Value` field, preventing false `No data` displays.

## [0.3.1] - 2026-09-08

This patch restores a reproducible clone-to-dashboard startup path and separates
versioned system definitions from mutable runtime state.

### Fixed

- Replaced the incompatible `numpy~=1.24.3` requirement. That range has no
  supported wheel for the current host Python and caused installation to fall
  back to a failing source build.
- Pinned the complete tested Python dependency set in `requirements.txt`.
  `pandas==2.3.2` is intentional: pandapower 3.1.2 fails during result
  extraction with pandas 3.x because the target array is read-only.
- Updated the simulator image to Python 3.12, which has wheels for the pinned
  numerical dependencies and is supported by pandapower 3.1.2.
- Made `BROKER_URL`, `PUB_TOPIC`, and `RATE_HZ` real simulator defaults. Compose
  previously supplied these variables, but `power_sim.py` ignored them and
  relied on separate CLI defaults.
- Aligned the default publisher and subscriber on `telemetry/pandapower` at
  1 Hz. CLI arguments still override all environment-derived defaults.
- Allowed file-mode output names without a parent directory instead of calling
  `os.makedirs("")`.
- Assigned the provisioned InfluxDB datasource the UID already referenced by
  the Grafana dashboard, so a fresh Grafana volume does not generate a
  different datasource identity.
- Changed Grafana's token lookup to `$INFLUXDB_READ_TOKEN`, avoiding Grafana's
  second interpolation pass when token values contain a dollar sign.
- Removed the misspelled `NFLUXDB_ADMIN_TOKEN` entry from `.env.example`.

### Added

- Added the active Node-RED definition at `nodered/data/flows.json` to version
  control. It contains no Node-RED credential object or embedded token value.
- Added `nodered/Dockerfile`, based on Node-RED 4.1.0, to install the exact
  `node-red-dashboard` version required by the tracked flow at image-build
  time. A fresh clone no longer depends on modules left in a developer's local
  Node-RED directory.
- Added `.dockerignore` so Git metadata, local environment files, virtual
  environments, telemetry, caches, and service state are not sent into Docker
  build contexts.

### Changed

- Reworked the Node-RED mounts: `/data` is a named volume for settings,
  credentials, caches, and other runtime state, while only the tracked
  `flows.json` is bind-mounted into it. Deliberate flow edits remain visible to
  Git; simply running Node-RED does not expose its entire data directory as
  repository changes.
- Moved Mosquitto data and logs from repository bind mounts to named volumes.
  InfluxDB and Grafana already used named volumes, so database and dashboard
  runtime state remains outside Git across the whole stack.
- Removed fixed container names so Compose can scope containers by project and
  avoid name collisions between clones.
- Bound all published ports to `127.0.0.1`, matching the development credential
  defaults and avoiding accidental LAN exposure.
- Replaced Grafana's broad `.env` import with explicit login and datasource
  variables. The container no longer receives the InfluxDB admin/write values
  or unrelated simulator settings.
- Pinned `node-red-dashboard` to 3.6.6 and the Node-RED base image to 4.1.0 so
  rebuilds do not silently select a new runtime or UI-node release.
- Changed the simulator Dockerfile to copy exactly `requirements.txt`; wildcard
  requirement copies could become ambiguous if another requirements file were
  added later.
- Updated `.gitignore` to ignore everything under `nodered/data` except
  `flows.json`, plus Mosquitto logs. Existing rules continue to ignore `.env`,
  virtual environments, Python caches, simulator output, Node modules, and
  broker data.
- Updated `.env.example` to use the actual telemetry topic and rate. Its
  `CHANGE_ME` credentials are development placeholders; read/write tokens use
  the bootstrap token in the quickstart and should be scoped for non-development
  deployments.
- Replaced the obsolete Quickstart with the supported Compose build path and
  documented startup, inspection, shutdown, URLs, state ownership, the
  clean-working-tree expectation, and an optional Python 3.12/3.13 host setup.

### Upgrade note

- v0.3.1 no longer mounts `nodered/data`, `mqtt/data`, or `mqtt/log` wholesale.
  Files already present in those ignored directories are left untouched, but
  new containers use Compose named volumes for mutable state. The tracked
  `flows.json` remains the source of the Node-RED system definition.

## [0.1.0] - 2025-09-26
### Added
- Initial repo scaffolding
- Python simulator emitting 1 Hz JSON telemetry (file and MQTT modes)
- Node-RED minimal flow (MQTT or file tail), Debug + Dashboard
- Started CHANGELOG.md
### Changed
- README.md shows ASCII architecture diagram and verification

## [0.2.0] - 2025-09-29
### Added
- 3-bus 20 kV pandapower model (slack + two loads, simple MV line params) with smooth 1 Hz variability.
- `--pandapower` flag in `power_sim.py` to stream physics-based telemetry to file or MQTT.
- New JSON schema for physics mode: `{"ts", "buses":[{"name","vm_pu","va_degree","p_mw","q_mvar"}]}`.
- Node-RED flow to parse `buses[]`, split per-bus, and show live values in Debug (optional Dashboard).

### Changed
- Default RNG in power_sim remains; pandapower mode is opt-in to keep setup easy on Windows.

### Docs
- ASCII single-line diagram and Node-RED screenshot in `/docs` (see `docs\dashbooard_v0_2_0.png`).

## [0.2.1] - 2025-09-29
### Fixed
- Python requirements.txt and in README were wrong, fixed now
    **paho-mqtt==1.6.1**
    **pandapower==3.1.2**
    **numpy==2.3.3**

## [0.3.0] - 2025-10-11
### Added

- InfluxDB v2 historian with bucket `scada`.
- Node-RED flow writing 1 Hz pandapower telemetry to Influx via HTTP Write API (line protocol).
- Grafana dashboard (Flux) with starter panels:
  - Bus Voltages (p.u.) grouped by `name`
  - Line Active Power P (MW) grouped by `name` and `end`
- Docker Compose stack (InfluxDB, Grafana, Node-RED, Mosquitto) for one-command bring-up.

### Changed
- .env.example
- README section with architecture ASCII and run instructions.
- node-red is now a docker container
- dashboard is now grafana container
- Standardized telemetry schema: `bus`, `line`, `ext_grid` measurements with clear tags/fields.:
    `{"ts","buses":[{"bus_idx","name","vm_pu","va_degree","p_mw","q_mvar"}],"lines":[{"line_idx","name","end","from_bus","to_bus","p_mw","q_mvar","pl_mw","ql_mvar","i_ka","vm_pu","va_degree","loading_percent"}],"ext_grid":{"p_mw","q_mvar"}}`.
