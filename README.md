# jspX v0.3.0 - joySCADA_Power X (Simulated Power System)

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

   [BUS0_SLACK] --L1(5 km)--> [BUS1_LOAD] --L2(3 km)--> [BUS2_LOAD]
       ext_grid                    ~1.2 MW / 0.3 MVAr        ~0.8 MW / 0.2 MVAr
       vm≈1.00 pu                  vm≈0.98–0.99 pu           vm≈0.97–0.99 pu

## Getting Started

### Prereqs
- **Windows 10** (tested). Linux/macOS should work with small path tweaks.
- **Python 3.x**
    - paho-mqtt==1.6.1
    - pandapower==3.1.2
    - numpy==2.3.3
- **Docker Container 28.x**


### Quickstart

```bash
# 1) clone/create your repo and enter it
# (See "Git init & tag" below)

# 2) create containers out of docker-compose file
docker compose up -d

# 3) Python env
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1   # PowerShell
# or: .venv\Scripts\activate   # cmd.exe
pip install -r requirements.txt
# 3) Run the simulator (file mode: stdout + append to data/telemetry.ndjson)
python src/power_sim.py --pandapower --mqtt   # mqtt protocol
# or: python src/power_sim.py --pandapower    # just file

# 4) See Grafana dashboard
# Node-RED UI:  http://localhost:1880
# Influx UI:    http://localhost:8086  
# Grafana UI:   http://localhost:3000 
```
### Verification
.\docs\dashboard_v0_3_0.png