# jspX - joySCADA_Power X (Simulated Power System)

A minimal, reproducible “Hello SCADA” loop for a simulated power portfolio:
- Python sim emits timestamped JSON lines (voltage/power) at 1 s intervals
- Ingest via MQTT **or** file tail into Node-RED *Review*
- Display latest values on Debug and optional Dashboard
- Clean structure, least privilege, and beginner-friendly

%% Layout
  classDef file fill:#222,stroke:#666,color:#fff;
  classDef app fill:#0b5,stroke:#083,color:#fff;
  classDef ui fill:#06c,stroke:#049,color:#fff;

  PS[/"power_sim.py"\nEmits JSON every 1s\n(Appends to file)/]:::app
  NDJSON[[data/telemetry.ndjson\n(NDJSON log)]]:::file

  subgraph NR[Node-RED]
    direction TB
    MQTTIN[[mqtt in\nsubscribe: telemetry/*]]
    JSONNODE[[json node]]
    DEBUG[[Debug sidebar]]:::ui
    DASH[[Dashboard gauges]]:::ui

    MQTTIN --> JSONNODE --> DEBUG
    JSONNODE --> DASH
  end

  PS -- "MQTT publish\ntelemetry/*" --> MQTTIN
  PS -- "file append" --> NDJSON

## Getting Started

### Prereqs
- **Windows 10** (tested). Linux/macOS should work with small path tweaks.
- **Python 3.x**
- **Node.js LTS** (for Node-RED)

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
python src/power_sim.py

# 4) Node-RED (first install globally; see below)
node-red
# open http://127.0.0.1:1880 , Import -> Clipboard -> paste flows/hello_scada_flow.json
# If using file-tail path: edit the Tail node to point to your absolute telemetry.ndjson path
# If using MQTT path: point MQTT node to your broker (localhost:1883 by default)
# Dashboard: http://127.0.0.1:1880/ui
