
**CHANGELOG.md**
```markdown
# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
