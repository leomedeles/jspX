# jspX v0.4.0 - joySCADA_Power X (Simulated Power System)

A minimal, reproducible SCADA loop for a simulated power portfolio:
- Python sim emits timestamped JSON lines (buses, lines, exrt_grid) at 1 s intervals
- Node-red ingest via MQTT **or** file tail into historian InfluxDB
- Display latest values on grafana dashboard
- Clean structure, least privilege, and beginner-friendly

flowchart TD
    A["power_sim.py<br>JSON/1s<br>file append"] -->|"telemetry/* (MQTT topic)"| B["Node-RED mqtt in"]
    B --> C["line protocol"]
    C -->|"http POST to scada bucket"| D["InfluxDB Historian"]
    D -->|"Flux query"| E["Grafana Dashboard"]
    A --> F["data/telemetry.ndjson"]

+----------------+       (MQTT topic)   +---------------------+
| power_sim.py   |  --->  telemetry/* ->| Node-RED mqtt in    |
|  JSON/1s       |                      +----------+----------+
|  file append   |                            | line protocol |
+-------+--------+                            +-------+-------+
        |                   http POST to scada bucket | 
        |                                             v
        |                                 +----------------------+
        |                                 | InfluxDB Historian   |
        |                                 +------------+---------+
        |                                   Flux query |  
        |                                              v
        |                                    +-------------------+
        |                                    | Grafana Dashboard |
        |                                    +-------------------+
        v
data/telemetry.ndjson

## Grid Model

20 kV feeder (3-bus minimal case)

   [BUS0_SLACK] --[BRK_L1_SOURCE]--L1(5 km)--> [BUS1_LOAD] --L2(3 km)--> [BUS2_LOAD]
       ext_grid                                      ~1.2 MW / 0.3 MVAr        ~0.8 MW / 0.2 MVAr
       vm≈1.00 pu                                    vm≈0.98–0.99 pu           vm≈0.97–0.99 pu

`BRK_L1_SOURCE` is a real pandapower line switch at the BUS0 end of L1. In v0.4, the simulator applies the authoritative `BreakerController`
state to this switch on a 50 ms control scan while retaining the configured
SCADA publication interval. When open, L1 current/loading is zero and the two
isolated downstream buses expose unavailable voltage/angle values as JSON
`null`, with `energized: false` and `quality: "NOT_ENERGIZED"`.

### Breaker MQTT contract

Pandapower MQTT mode listens for commands on three payload-independent topics:

| Purpose | Topic |
| --- | --- |
| Open | `cmd/breaker/open` |
| Close | `cmd/breaker/close` |
| Reset trip latch | `cmd/breaker/reset` |
| Authoritative status | `status/breaker` |

`status/breaker` is retained, so a newly connected HMI receives the latest
confirmed controller state without waiting for another operation. The simulator
publishes status only after its control loop has applied the controller state to
the physical switch. `RESET` clears the latch without closing, and `CLOSE` is
rejected while the latch remains active. The existing `telemetry/pandapower`
stream remains non-retained and is not the authoritative breaker-state topic.
The tracked Node-RED breaker HMI publishes the three command topics and subscribes
to retained `status/breaker`. It displays the authoritative state, protection/trip
indication and reason, and undervoltage alarm.

### Validation scenario MQTT contract

Pandapower MQTT mode subscribes to `cmd/sim/scenario/set`. Its payload must be
exactly one of `NORMAL`, `OVERCURRENT`, or `UNDERVOLTAGE` (uppercase UTF-8 with
no surrounding whitespace). Unknown or invalid payloads are rejected without
changing the selected scenario or plant inputs.

- `NORMAL` restores the 1.0 pu source setpoint and base downstream demand. It
  does not reset a protection latch or operate the breaker.
- `OVERCURRENT` applies five times the base downstream MW/MVAr demand without
  changing L1's current rating, allowing the existing protection to trip L1.
- `UNDERVOLTAGE` lowers the source setpoint to 0.90 pu. It asserts the existing
  downstream undervoltage alarm but does not directly trip L1.

## Getting started

### Prerequisites

- Docker Desktop with Docker Compose v2
- Git

Python is included in the simulator image, so it is not required on the host for the normal startup path.


### Quickstart

Clone the repository, enter it, and create the local environment file:

```powershell
Copy-Item .env.example .env
```

On Linux or macOS, use `cp .env.example .env` instead. The supplied values are development defaults and all ports bind to localhost. Change the credentials before exposing any service outside your computer.

Build and start the complete stack:

```powershell
docker compose up -d --build
docker compose ps
```

This starts the pandapower simulator, Mosquitto, Node-RED, InfluxDB, and Grafana. The simulator publishes one sample per second to `telemetry/pandapower`; the tracked Node-RED flow writes it to the `scada` bucket.

Node-RED also persists each authoritative `status/breaker` update as the
`breaker_status` measurement tagged `breaker=BRK_L1_SOURCE`. The provisioned
Grafana dashboard's Operations section reads that history from InfluxDB and
shows the current breaker position, trip latch, undervoltage alarm, and recent
status transitions.

Open:

- Node-RED: http://localhost:1880
- InfluxDB: http://localhost:8086
- Grafana: http://localhost:3000

To inspect startup problems:

```powershell
docker compose logs --tail 100 sim mosquitto nodered influxdb grafana
```

To stop the stack while retaining database and application state:

```powershell
docker compose down
```

Runtime state is stored in Docker named volumes. `.env`, simulator output, Node-RED credentials/settings/cache, database files, and broker data are ignored by Git. The system definition and `nodered/data/flows.json` are tracked, so running the stack should not create files that Git asks you to commit.

#### Why v0.3.1 tracks these files

- `requirements.txt` and `dockerfile` define a Python 3.12 numerical stack that has been build-tested and can complete a pandapower step. The full dependency set is pinned because pandapower 3.1.2 currently fails with pandas 3.x.
- `nodered/data/flows.json` is the deployable flow and is the only tracked file under Node-RED's data directory. Node-RED credentials, settings, installed modules, caches, and backups remain runtime data.
- `package.json` and `nodered/Dockerfile` install the UI nodes referenced by the flow into the image. A new clone does not rely on a pre-existing `node_modules` directory.
- `docker-compose.yml` stores mutable Node-RED, Mosquitto, InfluxDB, and Grafana data in named volumes. Only the flow file and read-only provisioning/configuration are mounted from tracked paths.
- `.dockerignore` keeps local state and secrets out of Docker build contexts; `.gitignore` keeps the same runtime artifacts out of commits.
- Grafana's datasource UID is fixed to the UID referenced by the tracked dashboard, making provisioning deterministic on an empty Grafana volume.

When upgrading an existing checkout, old files under `nodered/data`, `mqtt/data`, and `mqtt/log` are not deleted. The v0.3.1 Compose configuration stops mounting those directories as service state. Node-RED uses the tracked flow plus a named volume, and Mosquitto uses named data/log volumes.

### Run the simulator on the host (optional)

Python 3.12 and 3.13 are supported by the pinned requirements. On Windows, create a fresh virtual environment and install them without activating the environment:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
```

Start only the broker and run the simulator against the broker's localhost port:

```powershell
docker compose up -d mosquitto
.\.venv\Scripts\python src/power_sim.py --mqtt --pandapower
```

On Linux or macOS, use a Python 3.12 or 3.13 interpreter and `.venv/bin/python` in the equivalent commands. Omitting `--mqtt` writes to `data/telemetry.ndjson`; that generated file is ignored by Git.

### Historical verification

![Grafana dashboard showing bus voltage and line power](docs/dashboard_v0_3_0.png)
