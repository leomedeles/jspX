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
    assert one(flow, type="ui-group", name="Reference feeder")["page"] == page["id"]
    assert one(flow, id="ui_feeder")["group"] == one(flow, type="ui-group")["id"]


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


def run_function(function, messages, flow_values=None):
    if not shutil.which("node"):
        pytest.skip("Node.js is unavailable for executing Node-RED functions")
    script = """
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const memory = new Map();
const warnings = [];
const context = {get: key => memory.get(key), set: (key, value) => memory.set(key, value)};
const node = {warn: message => warnings.push(message)};
const shared = new Map(Object.entries(input.flow || {}));
const flow = {get: key => shared.get(key), set: (key, value) => shared.set(key,value)};
const fn = new Function('msg', 'node', 'context', 'flow', 'Date', input.func);
const outputs = input.messages.map(msg => fn(msg, node, context, flow, {parse:Date.parse, now:()=>msg._now ?? 1001}));
process.stdout.write(JSON.stringify({outputs, warnings}));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        input=json.dumps({"func": function["func"], "messages": messages, "flow": flow_values or {}}),
        text=True, encoding="utf-8", capture_output=True, check=True,
    )
    return json.loads(completed.stdout)


def named_status(breaker, state="CLOSED", tripped=False, reason=None, alarm=False):
    return {"ts": "2026-10-11T12:00:00.123Z", "breaker": breaker,
            "state": state, "tripped": tripped, "trip_reason": reason,
            "undervoltage_alarm": alarm}


def test_named_status_validation_preserves_identity_and_clears_unknown() -> None:
    flow = flow_nodes()
    by_id = {node["id"]: node for node in flow}
    source = one(flow, type="mqtt in", topic="status/breaker/+")
    transform = by_id[source["wires"][0][0]]
    assert transform["wires"] == [["fn_feeder_display"], ["fn_status_to_lp"]]
    def message(breaker, **kwargs):
        return {"topic": f"status/breaker/{breaker}", "payload": named_status(breaker, **kwargs)}
    outputs = run_function(transform, [
        {"topic": "status/bootstrap"},
        message("BRK_F1", state="OPEN", tripped=True, reason="overcurrent", alarm=True),
        message("BRK_F1", state="OPEN"),
        message("BRK_R1", tripped=True, reason="overcurrent"),
        {"topic": "status/breaker/BRK_F1", "payload": "{bad JSON"},
        {"topic": "status/breaker/BRK_R1", "payload": named_status("BRK_F1")},
        {"topic": "status/breaker/BRK_F1", "payload": {**named_status("BRK_F1"), "tripped": None}},
        message("BRK_X"),
        {"topic": "status/bootstrap"},
    ])["outputs"]
    assert [m["payload"]["breaker"] for m in outputs[0][0]] == ["BRK_F1", "BRK_R1"]
    assert all(not m["payload"]["valid"] for m in outputs[0][0])
    assert outputs[1][0]["payload"]["status"]["tripped"] is True
    cleared = outputs[2][0]["payload"]["status"]
    assert cleared["state"] == "OPEN" and cleared["trip_reason"] is None
    assert outputs[3][0]["payload"]["breaker"] == "BRK_R1"
    assert outputs[3][0]["payload"]["status"]["state"] == "CLOSED"
    for result in outputs[4:7]:
        assert result[0]["payload"]["valid"] is False
        assert result[0]["payload"]["status"] is None
        assert result[1] is None
    assert outputs[7] is None
    assert outputs[8] == [[], None]  # Late bootstrap never overwrites retained feedback.
    written = run_function(by_id['fn_status_to_lp'], [outputs[3][1]])["outputs"][0]
    assert 'state="CLOSED"' in written["payload"] and "tripped=true" in written["payload"]
    assert written["payload"].endswith(" 1791720000123")


@pytest.mark.parametrize("case", ["normal", "f1_open", "r1_open", "selective", "failure", "low_voltage"])
def test_display_snapshot_matches_solved_plant_and_physical_feedback(case) -> None:
    from src.power_grid import ReferenceFeederGrid
    from src.power_sim import ControlledPandapowerSimulator, breaker_status_payload
    grid = ReferenceFeederGrid.build(seed=1)
    simulator = ControlledPandapowerSimulator(grid)
    if case in ("f1_open", "r1_open"):
        grid.set_breaker_closed("BRK_F1" if case == "f1_open" else "BRK_R1", False)
    if case in ("selective", "failure", "low_voltage"):
        grid.set_scenario({"selective": grid.TAIL_OVERCURRENT_TEST,
                           "failure": grid.R1_OPENING_FAILURE_TEST,
                           "low_voltage": grid.LOW_SOURCE_VOLTAGE}[case])
    for time in (0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30):
        telemetry = simulator.control_step(timestamp=time)
    telemetry["buses"].reverse()
    telemetry["lines"].reverse()
    messages = [{"topic": "telemetry/pandapower", "payload": telemetry}]
    for breaker, controller in simulator.controllers.items():
        status = breaker_status_payload(controller, breaker, grid.breaker_is_closed(breaker))
        messages.append({"topic": "display/breaker", "payload": {"breaker": breaker, "valid": True, "status": status}})
    transform = one(flow_nodes(), id="fn_feeder_display")
    snapshot = run_function(transform, messages)["outputs"][-1]["payload"]
    assert snapshot["presence"] == "ONLINE"
    assert snapshot["assets"]["BUS_MV_SOURCE"]["supply"] == "ENERGIZED"
    for collection in ("buses", "lines", "transformers"):
        for record in telemetry[collection]:
            if collection == "lines" and record["end"] != "from":
                continue
            selected = snapshot["assets"][record["name"]]
            assert selected["supply"] == ("ENERGIZED" if record["energized"] else "DE-ENERGIZED")
            for field, value in selected["values"].items():
                assert value == record[field]
    remote = snapshot["assets"]["BUS_R1_REMOTE"]
    lv = snapshot["assets"]["BUS_SS1_LV"]
    assert (remote["supply"] == "ENERGIZED") == (case not in ("f1_open", "failure"))
    assert (lv["supply"] == "ENERGIZED") == (case in ("normal", "low_voltage"))
    r1 = snapshot["breakers"]["BRK_R1"]
    f1 = snapshot["breakers"]["BRK_F1"]
    assert r1["position"] == ("OPEN" if case in ("r1_open", "selective") else "CLOSED")
    assert r1["latch"] == ("TRIPPED" if case in ("selective", "failure") else "CLEAR")
    assert f1["position"] == ("OPEN" if case in ("f1_open", "failure") else "CLOSED")
    assert f1["alarm"] == ("UV ALARM" if case == "low_voltage" else "UV NORMAL")
    if case in ("r1_open", "selective"):
        assert snapshot["assets"]["L2_FEEDER_TAIL"]["values"]["i_ka"] == 0
        assert lv["values"]["vm_pu"] is None


def test_snapshot_unknown_partial_recovery_status_isolation_and_freshness() -> None:
    from src.power_grid import ReferenceFeederGrid
    import copy
    sample = ReferenceFeederGrid.build(seed=1).solve()
    partial = copy.deepcopy(sample)
    partial["buses"] = []
    partial["lines"][0]["quality"] = "NOT_ENERGIZED"  # Conflicting terminal metadata.
    partial["transformers"].append(partial["transformers"][0])
    function = one(flow_nodes(), id="fn_feeder_display")
    messages = [
        {"topic": "display/bootstrap", "_now": 1000},
        {"topic": "telemetry/pandapower", "payload": sample, "_now": 1000},
        {"topic": "display/breaker", "payload": {"breaker":"BRK_R1", "valid":True,
          "status":named_status("BRK_R1", tripped=True, reason="overcurrent")}, "_now":1001},
        {"topic": "display/breaker", "payload": {"breaker":"BRK_F1", "valid":False, "status":None}, "_now":1002},
        {"topic": "display/presence", "payload": "OFFLINE", "_now": 6000},
        {"topic": "display/presence", "payload": "ONLINE", "_now": 6001},
        {"topic": "telemetry/pandapower", "payload": partial, "_now":6002},
        {"topic": "display/breaker", "payload": {"breaker":"BRK_R1", "valid":True,
          "status":named_status("BRK_R1")}, "_now":6003},
        {"topic": "display/bootstrap", "_now":11002},
        {"topic": "telemetry/pandapower", "payload": "{bad", "_now":11003},
    ]
    results = run_function(function, messages)["outputs"]
    assert results[0]["payload"]["presence"] == "UNKNOWN"
    assert results[2]["payload"]["breakers"]["BRK_R1"]["enabled"] is True
    assert results[3]["payload"]["breakers"]["BRK_R1"]["latch"] == "TRIPPED"
    assert results[3]["payload"]["breakers"]["BRK_F1"]["enabled"] is False
    offline = results[4]["payload"]
    assert offline["presence"] == "OFFLINE"
    assert all(not b["enabled"] for b in offline["breakers"].values())
    assert all(v is None for a in offline["assets"].values() for v in a["values"].values())
    assert results[5] is None
    recovered = results[6]["payload"]
    for name in ("BUS_R1_REMOTE", "L1_FEEDER_HEAD", "T1_PRIMARY"):
        assert recovered["assets"][name]["supply"] == "UNKNOWN"
    assert recovered["assets"]["L2_FEEDER_TAIL"]["supply"] == "ENERGIZED"
    assert results[7]["payload"]["breakers"]["BRK_R1"]["reason"] is None
    assert results[8]["payload"]["presence"] == "OFFLINE"
    assert results[9]["payload"]["presence"] == "ONLINE"
    assert all(a["supply"] == "UNKNOWN" for a in results[9]["payload"]["assets"].values())


def test_missing_null_nonfinite_and_duplicate_quantities_do_not_become_zero() -> None:
    from src.power_grid import ReferenceFeederGrid
    sample = ReferenceFeederGrid.build(seed=1).solve()
    sample["buses"][0]["vm_pu"] = None
    del sample["buses"][1]["vm_pu"]
    sample["buses"][2]["vm_pu"] = "NaN"
    sample["buses"].append(sample["buses"][3])
    sample["lines"][0]["i_ka"] = 0.0
    sample["lines"][0]["p_mw"] = "Infinity"
    sample["lines"] = [r for r in sample["lines"] if not (r["name"] == "L2_FEEDER_TAIL" and r["end"] == "to")]
    output = run_function(one(flow_nodes(), id="fn_feeder_display"),
                          [{"topic":"telemetry/pandapower", "payload":sample}])["outputs"][0]["payload"]
    for name in ("GRID_110KV", "BUS_MV_SOURCE", "BUS_R1_REMOTE", "BUS_SS1_MV"):
        assert output["assets"][name]["values"]["vm_pu"] is None
    assert output["assets"]["L1_FEEDER_HEAD"]["values"]["i_ka"] == 0.0
    assert output["assets"]["L1_FEEDER_HEAD"]["values"]["p_mw"] is None
    assert output["assets"]["L2_FEEDER_TAIL"]["supply"] == "UNKNOWN"
    # Valid JSON can overflow a JavaScript number even without a NaN literal.
    overflowing_json = json.dumps(sample).replace('"vm_pu": null', '"vm_pu": 1e400', 1)
    overflow = run_function(one(flow_nodes(), id="fn_feeder_display"),
                            [{"topic": "telemetry/pandapower", "payload": overflowing_json}])["outputs"][0]["payload"]
    assert overflow["assets"]["GRID_110KV"]["values"]["vm_pu"] is None


def test_commands_require_explicit_click_valid_identity_and_available_feedback() -> None:
    flow = flow_nodes()
    function = one(flow, id="fn_feeder_command")
    outbound = one(flow, type="mqtt out")
    assert function["wires"] == [[outbound["id"]]]
    assert outbound["qos"] == "1" and outbound["retain"] == "false"
    state = {"presence":"ONLINE", "receivedAt":1000,
             "breakers":{"BRK_F1":{"valid":False}, "BRK_R1":{"valid":True,
                "status":named_status("BRK_R1", tripped=True, reason="overcurrent")}}}
    valid = [{"intent":"operator-command", "topic":f"cmd/breaker/BRK_R1/{action}", "_now":1001}
             for action in ("open", "close", "reset")]
    invalid = [
        {"topic":"display/snapshot", "payload":state},
        {"topic":"cmd/breaker/BRK_R1/open"},
        {"intent":"operator-command", "topic":"cmd/sim/scenario/set"},
        {"intent":"operator-command", "topic":"cmd/breaker/BRK_X/open"},
        {"intent":"operator-command", "topic":"cmd/breaker/BRK_F1/close"},
        {"intent":"operator-command", "topic":"cmd/breaker/BRK_R1/open", "_now":6000},
    ]
    result = run_function(function, valid + invalid, {"feederDisplay":state})["outputs"]
    assert [m["payload"] for m in result[:3]] == ["OPEN", "CLOSE", "RESET"]
    assert all(m is None for m in result[3:])
    state["presence"] = "OFFLINE"
    assert run_function(function, valid, {"feederDisplay":state})["outputs"] == [None]*3
    template = one(flow, id="ui_feeder")
    assert template["passthru"] is False and template["storeOutMessages"] is False
    assert template["wires"] == [[function["id"]]]


def test_template_formats_data_without_optimistic_feedback_or_command_replay() -> None:
    if not shutil.which("node"):
        pytest.skip("Node.js is unavailable for executing the Dashboard component")
    template = one(flow_nodes(), id="ui_feeder")["format"]
    component_script = template.split("<script>", 1)[1].split("</script>", 1)[0]
    script = """
const source = JSON.parse(require('fs').readFileSync(0,'utf8'));
const component = new Function(source.replace('export default', 'return'))();
const sent = [];
const socket = {connected:true, on:()=>{}, off:()=>{}};
global.ResizeObserver = class {observe(){} disconnect(){}};
global.setInterval = () => 1;
global.clearInterval = () => {};
const view = {...component.data(), $socket:socket, $refs:{view:{}}, send:m=>sent.push(m)};
for (const [key,fn] of Object.entries(component.methods)) view[key] = fn.bind(view);
for (const [key,fn] of Object.entries(component.computed)) Object.defineProperty(view,key,{get:fn.bind(view)});
component.mounted.call(view);
const snapshot = {presence:'ONLINE', telemetryAgeMs:0, assets:{
    BUS_MV_SOURCE:{supply:'ENERGIZED',values:{vm_pu:null}},
    L2_FEEDER_TAIL:{supply:'DE-ENERGIZED',values:{i_ka:0,p_mw:-1.25,q_mvar:0.5}}
},breakers:{BRK_R1:{position:'OPEN',latch:'TRIPPED',reason:'overcurrent',enabled:true}}};
const receive = () => component.watch.msg.handler.call(view,{topic:'display/snapshot',payload:snapshot});
receive();
const unavailable = view.measurement('BUS_MV_SOURCE','vm_pu',3,'pu');
snapshot.assets.BUS_MV_SOURCE.values.vm_pu = Number.NaN;
const nonfinite = view.measurement('BUS_MV_SOURCE','vm_pu',3,'pu');
const zero = view.measurement('L2_FEEDER_TAIL','i_ka',3,'kA');
const signed = view.measurement('L2_FEEDER_TAIL','p_mw',2,'MW');
view.command('BRK_R1','CLOSE');
view.command('BRK_F1','OPEN');
receive(); // Display replay must not send a second command.
const actual = view.breakerState('BRK_R1').position;
view.onDisconnect();
const disconnected = {presence:view.presence,enabled:view.canCommand('BRK_R1'),value:view.measurement('L2_FEEDER_TAIL','i_ka',3,'kA')};
view.onConnect();
const reconnectBeforeSnapshot = view.presence;
receive();
const recovered = view.presence;
view.clock = view.snapshotObservedAt + 5000;
const expired = {presence:view.presence,enabled:view.canCommand('BRK_R1')};
component.unmounted.call(view);
process.stdout.write(JSON.stringify({sent,actual,unavailable,nonfinite,zero,signed,disconnected,reconnectBeforeSnapshot,recovered,expired}));
"""
    completed = subprocess.run(["node", "-e", script], input=json.dumps(component_script),
                               text=True, encoding="utf-8", capture_output=True, check=True)
    result = json.loads(completed.stdout)
    assert result["sent"] == [{"intent": "operator-command",
                               "topic": "cmd/breaker/BRK_R1/close", "payload": "CLOSE"}]
    assert result["actual"] == "OPEN"
    assert result["unavailable"] == result["nonfinite"] == "— UNAVAILABLE"
    assert result["zero"] == "0.000 kA"
    assert result["signed"] == "-1.25 MW"
    assert result["disconnected"] == {"presence": "OFFLINE", "enabled": False, "value": "— OFFLINE"}
    assert result["reconnectBeforeSnapshot"] == "OFFLINE"
    assert result["recovered"] == "ONLINE"
    assert result["expired"] == {"presence": "OFFLINE", "enabled": False}


def test_single_telemetry_subscription_and_presence_transitions() -> None:
    flow = flow_nodes()
    by_id = {node["id"]: node for node in flow}
    telemetry = one(flow, type="mqtt in", topic="telemetry/pandapower")
    writer = one(flow, type="http request")
    assert writer["method"] == "POST"
    assert telemetry["broker"] == one(flow, type="mqtt-broker")["id"]
    assert path_count(by_id, telemetry["id"], writer["id"]) == 1
    assert len([n for n in flow if n["type"] == "mqtt in" and n["topic"] == telemetry["topic"]]) == 1
    trigger = one(flow, type="trigger")
    assert trigger["duration"] == "5" and trigger["units"] == "s" and trigger["extend"] is True
    assert path_count(by_id, telemetry["id"], trigger["id"]) == 1
    presence = by_id[trigger["wires"][0][0]]
    samples = run_function(presence, [{"payload":{"online":online}} for online in (True,True,False,False,True)])["outputs"]
    assert [s[0]["payload"] if s[0] else None for s in samples] == ["ONLINE",None,"OFFLINE",None,"ONLINE"]
    assert [s[1] is not None for s in samples] == [False,False,True,False,True]
    assert samples[0][0]["topic"] == "display/presence"
    telemetry_lp = next(by_id[target] for target in telemetry["wires"][0] if path_count(by_id,target,writer["id"]) == 1)
    sample = {"ts":"2026-10-11T12:00:00.123Z",
              "buses":[{"bus_idx":0,"name":"BUS_MV_SOURCE","vm_pu":1.0,"energized":True,"quality":"GOOD"}],
              "lines":[{"line_idx":0,"name":"L1_FEEDER_HEAD","energized":True,"quality":"GOOD"}],
              "transformers":[{"transformer_idx":0,"name":"T1_PRIMARY","hv_bus":0,"lv_bus":1,"energized":True,"quality":"GOOD"}],
              "ext_grid":{"grid_idx":0,"name":"GRID_110KV","p_mw":2.0}}
    line_protocol = run_function(telemetry_lp,[{"payload":sample}])["outputs"][0]["payload"]
    assert [line.split(',',1)[0] for line in line_protocol.splitlines()] == ["bus","line","transformer","ext_grid"]
    assert all(line.endswith(' 1791720000123') for line in line_protocol.splitlines())


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
