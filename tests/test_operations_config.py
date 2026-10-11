import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
FLOW_PATH = ROOT / "nodered" / "data" / "flows.json"
DASHBOARD_PATH = (
    ROOT / "grafana" / "provisioning" / "dashboards" / "scada-v030.json"
)
DATASOURCE_UID = "P951FEA4DE68E13C5"


def load_json(path: Path):
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def test_flowfuse_dashboard_is_the_only_active_hmi() -> None:
    package = load_json(ROOT / "package.json")
    flow = load_json(FLOW_PATH)
    dockerfile = (ROOT / "nodered" / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert package["dependencies"] == {"@flowfuse/node-red-dashboard": "1.32.0"}
    assert '"@flowfuse/node-red-dashboard@${dashboard_version}"' in dockerfile
    assert "jspx-nodered:4.1.0-flowfuse-1.32.0" in compose
    assert not any(node["type"].startswith("ui_") for node in flow)
    base = one(flow, type="ui-base")
    page = one(flow, type="ui-page")
    theme = one(flow, type="ui-theme")
    one(flow, type="ui-notification")
    assert base["path"] == "/dashboard"
    assert page["ui"] == base["id"]
    assert page["path"] == "/"
    assert page["theme"] == theme["id"]
    for breaker in ("BRK_F1", "BRK_R1"):
        assert one(flow, type="ui-group", name=breaker)["page"] == page["id"]


def flow_nodes():
    return load_json(FLOW_PATH)


def one(nodes, **properties):
    matches = [
        node for node in nodes
        if all(node.get(key) == value for key, value in properties.items())
    ]
    assert len(matches) == 1, properties
    return matches[0]


def path_count(by_id, start, target):
    if start == target:
        return 1
    return sum(
        path_count(by_id, downstream, target)
        for output in by_id[start].get("wires", [])
        for downstream in output
        if downstream in by_id
    )


def run_function(function, messages):
    if not shutil.which("node"):
        pytest.skip("Node.js is unavailable for executing Node-RED functions")
    script = """
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const memory = new Map();
const warnings = [];
const context = {get: key => memory.get(key), set: (key, value) => memory.set(key, value)};
const node = {warn: message => warnings.push(message)};
const fn = new Function('msg', 'node', 'context', input.func);
const outputs = input.messages.map(msg => fn(msg, node, context));
process.stdout.write(JSON.stringify({outputs, warnings}));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        input=json.dumps({"func": function["func"], "messages": messages}),
        text=True, capture_output=True, check=True,
    )
    return json.loads(completed.stdout)


def test_named_commands_and_status_are_isolated_and_unknown_is_visible() -> None:
    flow = flow_nodes()
    by_id = {node["id"]: node for node in flow}
    assert len([node for node in flow if node["type"] == "mqtt-broker"]) == 1
    broker = one(flow, type="mqtt-broker")
    outbound = one(flow, type="mqtt out")
    assert outbound["broker"] == broker["id"]
    assert outbound["qos"] == "1"
    assert outbound["retain"] == "false"

    status_input = one(flow, type="mqtt in", topic="status/breaker/+")
    assert [
        node for node in flow
        if node["type"] == "mqtt in"
        and node["topic"].startswith("status/breaker/")
    ] == [status_input]
    assert status_input["broker"] == broker["id"]
    assert status_input["datatype"] == "utf8"
    assert status_input["rh"] == 0
    assert len(status_input["wires"][0]) == 1
    transform_id = status_input["wires"][0][0]
    transform = by_id[transform_id]
    assert transform["type"] == "function"

    for breaker in ("BRK_F1", "BRK_R1"):
        group = one(flow, type="ui-group", name=breaker)
        for action in ("open", "close", "reset"):
            button = one(flow, type="ui-button",
                         topic=f"cmd/breaker/{breaker}/{action}")
            assert button["group"] == group["id"]
            assert button["payload"] == action.upper()
            assert button["wires"] == [[outbound["id"]]]

    outputs = transform["wires"]
    def output_index(breaker, label):
        group = one(flow, type="ui-group", name=breaker)
        widget = one(flow, type="ui-text", group=group["id"], label=label)
        matches = [i for i, targets in enumerate(outputs) if widget["id"] in targets]
        assert len(matches) == 1
        return matches[0]

    f1 = {label: output_index("BRK_F1", label)
          for label in ("State", "Trip latch", "Trip reason", "Undervoltage")}
    r1 = {label: output_index("BRK_R1", label)
          for label in ("State", "Trip latch", "Trip reason")}
    assert set(f1.values()).isdisjoint(r1.values())

    ts = "2026-10-11T12:00:00.123Z"
    def status(breaker, state, tripped, reason, alarm=False):
        return {"ts": ts, "breaker": breaker, "state": state,
                "tripped": tripped, "trip_reason": reason,
                "undervoltage_alarm": alarm}
    messages = [
        {"topic": "status/bootstrap", "payload": ""},
        {"topic": "status/breaker/BRK_F1",
         "payload": json.dumps(status("BRK_F1", "OPEN", True, "overcurrent", True))},
        {"topic": "status/breaker/BRK_F1",
         "payload": json.dumps(status("BRK_F1", "OPEN", False, None))},
        {"topic": "status/breaker/BRK_R1",
         "payload": json.dumps(status("BRK_R1", "CLOSED", True, "overcurrent"))},
        {"topic": "status/breaker/BRK_F1", "payload": "{bad JSON"},
        {"topic": "status/breaker/BRK_R1",
         "payload": json.dumps(status("BRK_F1", "OPEN", False, None))},
        {"topic": "status/breaker/BRK_F1",
         "payload": json.dumps({"ts": ts, "breaker": "BRK_F1",
                                "state": "CLOSED", "trip_reason": None,
                                "undervoltage_alarm": False})},
        {"topic": "status/breaker/BRK_X",
         "payload": json.dumps(status("BRK_X", "CLOSED", False, None))},
    ]
    results = run_function(transform, messages)["outputs"]
    assert all(results[0][i]["payload"] == "UNKNOWN" for i in
               list(f1.values()) + list(r1.values()))
    assert results[1][f1["State"]]["payload"] == "OPEN"
    assert results[1][f1["Trip latch"]]["payload"] == "TRIPPED"
    assert results[1][f1["Trip reason"]]["payload"] == "overcurrent"
    assert results[1][f1["Undervoltage"]]["payload"] == "ALARM"
    assert all(results[1][i] is None for i in r1.values())
    assert results[2][f1["Trip latch"]]["payload"] == "OK"
    assert results[2][f1["Trip reason"]]["payload"] == "-"
    assert results[2][f1["Undervoltage"]]["payload"] == "NORMAL"
    assert results[3][r1["State"]]["payload"] == "CLOSED"
    assert results[3][r1["Trip latch"]]["payload"] == "TRIPPED"
    assert all(results[3][i] is None for i in f1.values())
    for result, own, other in ((results[4], f1, r1), (results[5], r1, f1),
                               (results[6], f1, r1)):
        assert all(result[i]["payload"] == "UNKNOWN" for i in own.values())
        assert all(result[i] is None for i in other.values())

    historian_index = next(
        i for i, targets in enumerate(outputs)
        if any(by_id[target]["type"] == "function" for target in targets)
    )
    assert results[1][historian_index]["payload"]["breaker"] == "BRK_F1"
    assert results[3][historian_index]["payload"]["breaker"] == "BRK_R1"
    assert results[4][historian_index] is None
    assert results[5][historian_index] is None
    assert results[6][historian_index] is None
    assert results[7] is None
    status_lp = by_id[outputs[historian_index][0]]
    written = run_function(status_lp, [results[3][historian_index]])["outputs"][0]
    assert written["payload"].startswith("breaker_status,breaker=BRK_R1 ")
    assert 'state="CLOSED"' in written["payload"]
    assert "tripped=true" in written["payload"]
    assert written["payload"].endswith(" 1791720000123")


def test_single_telemetry_subscription_and_presence_transitions() -> None:
    flow = flow_nodes()
    by_id = {node["id"]: node for node in flow}
    telemetry = one(flow, type="mqtt in", topic="telemetry/pandapower")
    writer = one(flow, type="http request")
    assert writer["method"] == "POST"
    assert telemetry["broker"] == one(flow, type="mqtt-broker")["id"]
    assert path_count(by_id, telemetry["id"], writer["id"]) == 1

    plant = one(flow, type="ui-text", label="Plant")
    # ONLINE and timeout OFFLINE converge on one transition function.
    assert path_count(by_id, telemetry["id"], plant["id"]) == 2
    trigger = one(flow, type="trigger")
    assert trigger["duration"] == "5"
    assert trigger["units"] == "s"
    assert trigger["extend"] is True
    assert path_count(by_id, telemetry["id"], trigger["id"]) == 1
    presence = by_id[trigger["wires"][0][0]]
    assert presence["type"] == "function"
    samples = run_function(presence, [
        {"payload": {"online": True}},
        {"payload": {"online": True}},
        {"payload": {"online": False}},
        {"payload": {"online": False}},
        {"payload": {"online": True}},
    ])["outputs"]
    assert [sample[0]["payload"] if sample[0] else None for sample in samples] == [
        "ONLINE", None, "OFFLINE", None, "ONLINE"
    ]
    assert [sample[1] is not None for sample in samples] == [
        False, False, True, False, True
    ]

    telemetry_lp = next(
        by_id[target] for target in telemetry["wires"][0]
        if path_count(by_id, target, writer["id"]) == 1
    )
    sample = {"ts": "2026-10-11T12:00:00.123Z",
              "buses": [{"bus_idx": 0, "name": "BUS_MV_SOURCE",
                         "vm_pu": 1.0, "energized": True, "quality": "GOOD"}],
              "lines": [{"line_idx": 0, "name": "L1_FEEDER_HEAD",
                         "energized": True, "quality": "GOOD"}],
              "transformers": [{"transformer_idx": 0, "name": "T1_PRIMARY",
                                "hv_bus": 0, "lv_bus": 1,
                                "energized": True, "quality": "GOOD"}],
              "ext_grid": {"grid_idx": 0, "name": "GRID_110KV", "p_mw": 2.0}}
    line_protocol = run_function(telemetry_lp, [{"payload": sample}])["outputs"][0]["payload"]
    assert [line.split(",", 1)[0] for line in line_protocol.splitlines()] == [
        "bus", "line", "transformer", "ext_grid"
    ]
    assert all(line.endswith(" 1791720000123") for line in line_protocol.splitlines())


def test_ied_events_keep_identity_timestamp_and_immediate_write_path() -> None:
    flow = flow_nodes()
    by_id = {node["id"]: node for node in flow}
    event_input = one(flow, type="mqtt in", topic="event/ied")
    writer = one(flow, type="http request")
    assert event_input["broker"] == one(flow, type="mqtt-broker")["id"]
    assert event_input["rh"] == 0
    assert path_count(by_id, event_input["id"], writer["id"]) == 1
    parser = by_id[event_input["wires"][0][0]]
    assert parser["type"] == "json"
    transform = by_id[parser["wires"][0][0]]
    sample = {
        "ts": "2026-09-28T12:00:00.100Z",
        "event_id": "a" * 32 + ":5",
        "ied": "IED_R1", "breaker": "BRK_R1",
        "event": "POSITION_FEEDBACK", "scan_monotonic_s": 21.1,
        "position": "CLOSED", "tripped": True, "requested_state": "OPEN",
        "actual_state": "CLOSED", "success": False, "cause": "protection",
    }
    second = {**sample, "event_id": "a" * 32 + ":6"}
    lines = [run_function(transform, [{"payload": event}])["outputs"][0]["payload"]
             for event in (sample, second)]
    assert all(line.startswith("ied_event,ied=IED_R1,breaker=BRK_R1,")
               for line in lines)
    assert "event_id=" + sample["event_id"] in lines[0]
    assert "event_id=" + second["event_id"] in lines[1]
    assert lines[0] != lines[1]
    assert all(line.endswith(" 1790596800100") for line in lines)
    assert 'position="CLOSED"' in lines[0]
    assert 'requested_state="OPEN"' in lines[0]
    assert "success=false" in lines[0]
    bad = {**sample, "ied": "IED_F1"}
    assert run_function(transform, [{"payload": bad}])["outputs"][0] is None


def test_influx_writer_and_routine_debug_are_consolidated() -> None:
    flow = flow_nodes()
    by_id = {node["id"]: node for node in flow}
    writer = one(flow, type="http request")
    header = next(
        node for node in flow
        if node["type"] == "function" and node["wires"] == [[writer["id"]]]
    )
    for topic in ("telemetry/pandapower", "status/breaker/+", "event/ied"):
        source = one(flow, type="mqtt in", topic=topic)
        assert path_count(by_id, source["id"], header["id"]) == 1
    assert not any(node["type"] == "debug" and node.get("active")
                   for node in flow)
    assert writer["wires"][0]
    diagnostic = by_id[writer["wires"][0][0]]
    assert diagnostic["type"] == "function"
    assert one(flow, type="catch")["wires"] == [[diagnostic["id"]]]
    warnings = run_function(diagnostic, [
        {"statusCode": 204},
        {"statusCode": 401},
        {"error": {"message": "connection refused"}},
    ])["warnings"]
    assert len(warnings) == 2
    assert "401" in warnings[0]
    assert "connection refused" in warnings[1]
    assert not any(node.get("name", "").startswith("Legacy") for node in flow)


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
        "BRK_F1 State": ("stat", "BRK_F1"),
        "BRK_F1 Trip Latch": ("stat", "BRK_F1"),
        "BRK_R1 State": ("stat", "BRK_R1"),
        "BRK_R1 Trip Latch": ("stat", "BRK_R1"),
        "F1 Source-MV Undervoltage Alarm": ("stat", "BRK_F1"),
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
    assert 'r._measurement == "transformer"' in topology_query
    assert 'r._field == "energized"' in topology_query
    for asset in (
        "BUS_MV_SOURCE",
        "BUS_R1_REMOTE",
        "BUS_SS1_MV",
        "BUS_SS1_LV",
        "L1_FEEDER_HEAD",
        "L2_FEEDER_TAIL",
        "T1_PRIMARY",
        "T2_SS1",
    ):
        assert asset in topology_query

    transformer_loading = panels["Transformer Loading (%)"]
    assert transformer_loading["type"] == "timeseries"
    assert transformer_loading["datasource"]["uid"] == DATASOURCE_UID
    loading_query = transformer_loading["targets"][0]["query"]
    assert 'r._measurement == "transformer"' in loading_query
    assert 'r._field == "loading_percent"' in loading_query
    assert 'group(columns: ["name"])' in loading_query


def test_bus_voltage_panel_disconnects_missing_telemetry_samples() -> None:
    dashboard = load_json(DASHBOARD_PATH)
    panels = {panel["title"]: panel for panel in dashboard["panels"]}
    voltage_panel = panels["Bus Voltages (p.u.)"]
    graph_options = voltage_panel["fieldConfig"]["defaults"]["custom"]

    # Routine samples arrive every second. A missing voltage sample therefore
    # makes adjacent valid points about two seconds apart and must break the line.
    assert graph_options["insertNulls"] == 1500
    assert graph_options["spanNulls"] is False
