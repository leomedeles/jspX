# jspX - joySCADA_Power X (Simulated Power System)

A minimal, reproducible “Hello SCADA” loop for a simulated power portfolio:
- Python sim emits timestamped JSON lines (voltage/power) at 1 s intervals
- Ingest via MQTT **or** file tail into Node-RED
- Display latest values on Debug and optional Dashboard
- Clean structure, least privilege, and beginner-friendly

+----------------+       (MQTT)         +---------------------+
| power_sim.py   |  --->  telemetry/* ->| Node-RED mqtt in    |
|  JSON/1s       |                      +----------+----------+
|  file append   |---- file: ndjson ---------------->| json   |
+-------+--------+                                   +----+---+
        |                                                  |
        |                                                  v
        |                                        +------------------+
        |                                        | Debug sidebar    |
        |                                        +------------------+
        |                                        +------------------+
        |                                        | Dashboard gauges |
        |                                        +------------------+
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
- **Node.js LTS** (for Node-RED)
- **mqtt broker**
    - Mosquitto Broker **or** embedded node-red

### Quickstart

```bash
# 1) clone/create your repo and enter it
# (See "Git init & tag" below)

# 2) Python env
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1   # PowerShell
# or: .venv\Scripts\activate   # cmd.exe
pip install -r requirements.txt
# 3) Run the simulator (file mode: stdout + append to data/telemetry.ndjson)
# if mosquito: net start mosquitto
python src/power_sim.py --pandapower    # file mode
# or: python src/power_sim.py --pandapower --mqtt    # mqtt mode

# 4) Node-RED (first install globally; see below)
node-red
# open http://127.0.0.1:1880 , Import -> Clipboard -> paste flows/hello_scada_flow.json
# If using file-tail path: edit the Tail node to point to your absolute telemetry.ndjson path
# If using MQTT path: point MQTT node to your broker (localhost:1883 by default)
# Dashboard: http://127.0.0.1:1880/ui
```
### Verification
.\docs\dashbooard_v0_1_0.png
.\docs\dashbooard_v0_2_0.png