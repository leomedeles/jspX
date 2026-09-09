import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FLOW_PATH = ROOT / "nodered" / "data" / "flows.json"
DASHBOARD_PATH = (
    ROOT / "grafana" / "provisioning" / "dashboards" / "scada-v030.json"
)
DATASOURCE_UID = "P951FEA4DE68E13C5"


def load_json(path: Path):
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def test_authoritative_status_is_written_with_required_influx_schema() -> None:
    flow = load_json(FLOW_PATH)
    nodes = {node["id"]: node for node in flow}

    assert nodes["mqtt_in_status"]["topic"] == "status/breaker"
    assert "fn_status_to_lp" in nodes["json_parse"]["wires"][0]

    transform = nodes["fn_status_to_lp"]
    function = transform["func"]
    assert "Date.parse(p.ts)" in function
    assert "breaker_status,breaker=BRK_L1_SOURCE" in function
    for field in ("state", "tripped", "undervoltage_alarm", "trip_reason"):
        assert field in function
    assert transform["wires"] == [["917c308f0b48aa53"]]
    assert nodes["917c308f0b48aa53"]["wires"] == [["http_influx_write"]]
    assert nodes["http_influx_write"]["method"] == "POST"


def test_existing_telemetry_influx_path_is_preserved() -> None:
    flow = load_json(FLOW_PATH)
    nodes = {node["id"]: node for node in flow}

    telemetry_input = nodes["eea53fe7b525fcf9"]
    assert telemetry_input["topic"] == "telemetry/pandapower"
    assert "7d88f8edcae91d28" in telemetry_input["wires"][0]

    function = nodes["7d88f8edcae91d28"]["func"]
    assert "`bus,${tags}" in function
    assert "`line,${tags}" in function
    assert "`ext_grid,site=main" in function
    assert nodes["7d88f8edcae91d28"]["wires"] == [["ad39eed653b0a057"]]
    assert nodes["ad39eed653b0a057"]["wires"] == [["http-write"]]


def test_existing_dashboard_contains_influx_backed_operations_panels() -> None:
    dashboard = load_json(DASHBOARD_PATH)
    panels = {panel["title"]: panel for panel in dashboard["panels"]}

    assert dashboard["uid"] == "scada-v030"
    assert len({panel["id"] for panel in dashboard["panels"]}) == len(
        dashboard["panels"]
    )
    assert panels["Bus Voltages (p.u.)"]["type"] == "timeseries"
    assert panels["Line Active Power P (MW)"]["type"] == "timeseries"

    expected_types = {
        "Breaker State": "stat",
        "Trip Latch": "stat",
        "Undervoltage Alarm": "stat",
        "Recent Breaker / Protection Status": "table",
    }
    for title, panel_type in expected_types.items():
        panel = panels[title]
        assert panel["type"] == panel_type
        assert panel["datasource"]["uid"] == DATASOURCE_UID
        query = panel["targets"][0]["query"]
        assert 'r._measurement == "breaker_status"' in query
        assert 'r.breaker == "BRK_L1_SOURCE"' in query

    for title in ("Breaker State", "Trip Latch", "Undervoltage Alarm"):
        panel = panels[title]
        assert panel["options"]["colorMode"] == "background"
        assert panel["fieldConfig"]["defaults"]["mappings"]
        assert '|> keep(columns: ["_value"])' in panel["targets"][0][
            "query"
        ]

    history_query = panels["Recent Breaker / Protection Status"]["targets"][0][
        "query"
    ]
    assert "pivot(" in history_query
    for field in ("state", "tripped", "undervoltage_alarm", "trip_reason"):
        assert field in history_query
