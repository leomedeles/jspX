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

    assert nodes["mqtt_in_status"]["topic"] == (
        "status/breaker/BRK_L1_SOURCE"
    )
    assert "fn_status_to_lp" in nodes["json_parse"]["wires"][0]
    assert "fn_status_to_lp" in nodes["json_parse_l2"]["wires"][0]

    transform = nodes["fn_status_to_lp"]
    function = transform["func"]
    assert "Date.parse(p.ts)" in function
    assert 'p.breaker' in function
    assert '"BRK_L1_SOURCE", "BRK_L2"' in function
    assert "breaker_status,breaker=${breaker}" in function
    for field in ("state", "tripped", "undervoltage_alarm", "trip_reason"):
        assert field in function
    assert transform["wires"] == [["917c308f0b48aa53"]]
    assert nodes["917c308f0b48aa53"]["wires"] == [["http_influx_write"]]
    assert nodes["http_influx_write"]["method"] == "POST"


def test_hmi_operates_and_displays_both_named_breakers() -> None:
    flow = load_json(FLOW_PATH)
    nodes = {node["id"]: node for node in flow}

    expected = {
        "l1": {
            "group": "ui_group_main",
            "breaker": "BRK_L1_SOURCE",
            "buttons": ("btn_open", "btn_close", "btn_reset"),
            "status": "mqtt_in_status",
            "parser": "json_parse",
            "display": ("ui_state_text", "ui_trip_text", "ui_trip_reason"),
        },
        "l2": {
            "group": "ui_group_l2",
            "breaker": "BRK_L2",
            "buttons": ("btn_open_l2", "btn_close_l2", "btn_reset_l2"),
            "status": "mqtt_in_status_l2",
            "parser": "json_parse_l2",
            "display": (
                "ui_state_text_l2",
                "ui_trip_text_l2",
                "ui_trip_reason_l2",
            ),
        },
    }
    actions = ("open", "close", "reset")

    for definition in expected.values():
        group = definition["group"]
        breaker = definition["breaker"]
        assert nodes[group]["name"] == breaker
        for button_id, action in zip(definition["buttons"], actions):
            button = nodes[button_id]
            assert button["group"] == group
            assert button["topic"] == f"cmd/breaker/{breaker}/{action}"
            assert button["wires"] == [["mqtt_out_cmd"]]

        status = nodes[definition["status"]]
        assert status["topic"] == f"status/breaker/{breaker}"
        assert status["rh"] == 0
        assert status["wires"] == [[definition["parser"]]]
        parser_outputs = nodes[definition["parser"]]["wires"][0]
        for display_id in definition["display"]:
            assert nodes[display_id]["group"] == group
            assert display_id in parser_outputs or any(
                display_id in nodes[node_id]["wires"][0]
                for node_id in parser_outputs
                if nodes[node_id]["wires"]
            )


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
    assert "`energized=${!!b.energized}`" in function
    assert "`quality=${JSON.stringify(b.quality)}`" in function
    assert "`energized=${!!l.energized}`" in function
    assert "`quality=${JSON.stringify(l.quality)}`" in function
    assert "l.loading_percent != null" in function
    assert "Number(l.loading_percent)" in function
    assert "l.loading_pct" not in function
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

    breaker_panels = {
        "BRK_L1_SOURCE State": ("stat", "BRK_L1_SOURCE"),
        "BRK_L1_SOURCE Trip Latch": ("stat", "BRK_L1_SOURCE"),
        "BRK_L2 State": ("stat", "BRK_L2"),
        "BRK_L2 Trip Latch": ("stat", "BRK_L2"),
        "L1 Undervoltage Alarm": ("stat", "BRK_L1_SOURCE"),
    }
    for title, (panel_type, breaker_name) in breaker_panels.items():
        panel = panels[title]
        assert panel["type"] == panel_type
        assert panel["datasource"]["uid"] == DATASOURCE_UID
        query = panel["targets"][0]["query"]
        assert 'r._measurement == "breaker_status"' in query
        assert f'r.breaker == "{breaker_name}"' in query

    for title in breaker_panels:
        panel = panels[title]
        assert panel["options"]["colorMode"] == "background"
        assert panel["fieldConfig"]["defaults"]["mappings"]
        assert '|> keep(columns: ["_time", "_value"])' in panel["targets"][
            0
        ]["query"]
        assert panel["options"]["reduceOptions"]["fields"] == "Value"

    history_query = panels["Recent Breaker / Protection Status"]["targets"][0][
        "query"
    ]
    assert "pivot(" in history_query
    assert 'rowKey: ["_time", "breaker"]' in history_query
    for field in ("state", "tripped", "undervoltage_alarm", "trip_reason"):
        assert field in history_query

    topology = panels["Feeder Topology Energization"]
    assert topology["type"] == "table"
    assert topology["datasource"]["uid"] == DATASOURCE_UID
    topology_query = topology["targets"][0]["query"]
    assert 'r._measurement == "bus" or r._measurement == "line"' in (
        topology_query
    )
    assert 'r._field == "energized"' in topology_query
    for asset in ("BUS1_LOAD", "BUS2_LOAD", "L1_5km", "L2_3km"):
        assert asset in topology_query
