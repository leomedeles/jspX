#!/usr/bin/env python3
import json
import os
import signal
import sys
from time import monotonic_ns

import paho.mqtt.client as mqtt

# ---- Config (env with sane defaults) ----
BROKER_HOST = os.getenv("BROKER_HOST", "mosquitto")
BROKER_PORT = int(os.getenv("BROKER_PORT", "1883"))
TELE_TOPIC = os.getenv("TELEMETRY_TOPIC", "telemetry/main")
CMD_TOPIC = os.getenv("CMD_TOPIC", "cmd/breaker/main/set")
RESET_TOPIC = os.getenv("RESET_TOPIC", "cmd/breaker/main/reset")
STATUS_TOPIC = os.getenv("STATUS_TOPIC", "status/breaker/main")

OC_LINE_NAME = os.getenv("OC_LINE_NAME", "L1_5km")
OC_LINE_END = os.getenv("OC_LINE_END", "from")  # "from" | "to"
OC_TRIP_PCT = float(os.getenv("OC_TRIP_PCT", "120"))  # >= this -> start timing
TRIP_DELAY_MS = int(os.getenv("TRIP_DELAY_MS", "100"))  # 50-200 ms window

UV_BUS1 = os.getenv("UV_BUS1", "BUS1_LOAD")
UV_BUS2 = os.getenv("UV_BUS2", "BUS2_LOAD")
UV_ALARM_PU = float(os.getenv("UV_ALARM_PU", "0.92"))
UV_CLEAR_PU = float(os.getenv("UV_CLEAR_PU", "0.94"))

# ---- State ----
state = "OPEN"  # "OPEN"|"CLOSED" commanded/relayed
tripped = False  # latched
uv_alarm = False  # hysteresis (non-latched)
oc_start = None  # ns when OC condition began
trip_ns = None  # last trip latency (ns)
trip_reason = None

TRIP_WINDOW_NS = TRIP_DELAY_MS * 1_000_000


# ---- Helpers ----
def publish_status(client, *, reason=None, t_trip_ns=None):
    out = {"state": state, "tripped": tripped, "uv_alarm": uv_alarm}
    if reason is not None:
        out["reason"] = reason
    if t_trip_ns is not None:
        out["t_trip_ms"] = round(t_trip_ns / 1_000_000.0, 1)
    payload = json.dumps(out, separators=(",", ":"))
    # Retained so dashboards sync on reconnect
    client.publish(STATUS_TOPIC, payload, qos=0, retain=True)


def find_line_loading(snapshot):
    for line in snapshot.get("lines", []):
        if line.get("name") == OC_LINE_NAME and str(line.get("end")).lower() == OC_LINE_END:
            return float(line.get("loading_percent", 0.0))
    return None


def bus_vm(snapshot, name):
    for bus in snapshot.get("buses", []):
        if bus.get("name") == name:
            return float(bus.get("vm_pu", 0.0))
    return None


def update_uv(vm1, vm2):
    global uv_alarm
    if vm1 is None or vm2 is None:
        return False  # nothing to do
    prev = uv_alarm
    if prev:
        uv_alarm = not (vm1 >= UV_CLEAR_PU and vm2 >= UV_CLEAR_PU)
    else:
        uv_alarm = vm1 < UV_ALARM_PU or vm2 < UV_ALARM_PU
    return uv_alarm != prev


def trip_now(client, reason="overcurrent"):
    global tripped, state, oc_start, trip_ns, trip_reason
    tripped = True
    trip_reason = reason
    tnow = monotonic_ns()
    trip_ns = (tnow - oc_start) if oc_start else None
    state = "OPEN"
    oc_start = None
    publish_status(client, reason=trip_reason, t_trip_ns=trip_ns)


def handle_telem(client, payload_bytes):
    global oc_start
    try:
        data = (
            json.loads(payload_bytes.decode("utf-8"))
            if isinstance(payload_bytes, (bytes, bytearray))
            else payload_bytes
        )
        vm1 = bus_vm(data, UV_BUS1)
        vm2 = bus_vm(data, UV_BUS2)
        updated_uv = update_uv(vm1, vm2)

        load_pct = find_line_loading(data)
        tnow = monotonic_ns()
        if (
            state == "CLOSED"
            and not tripped
            and load_pct is not None
            and load_pct >= OC_TRIP_PCT
        ):
            if oc_start is None:
                oc_start = tnow
            elif (tnow - oc_start) >= TRIP_WINDOW_NS:
                trip_now(client, reason="overcurrent")
                return
        else:
            oc_start = None

        if updated_uv:
            publish_status(client)
    except Exception as exc:  # surface parsing errors without killing the loop
        client.publish(
            STATUS_TOPIC,
            json.dumps(
                {"state": state, "tripped": tripped, "uv_alarm": uv_alarm, "error": str(exc)}
            ),
            qos=0,
            retain=False,
        )


def handle_command(client, topic, payload_bytes):
    global state
    cmd = payload_bytes.decode("utf-8").strip().upper()
    if topic == CMD_TOPIC:
        if cmd == "CLOSE":
            if tripped:
                publish_status(client)  # reaffirm state/tripped
            else:
                state = "CLOSED"
                publish_status(client)
        elif cmd == "OPEN":
            state = "OPEN"
            publish_status(client)
    elif topic == RESET_TOPIC and tripped:
        clear_trip(client)


def clear_trip(client):
    global tripped, trip_reason
    tripped = False
    trip_reason = None
    publish_status(client)


# ---- MQTT glue ----
client = mqtt.Client(client_id=f"relay-{os.getpid()}", clean_session=True)


def on_connect(cl, userdata, flags, rc):
    cl.subscribe([(TELE_TOPIC, 0), (CMD_TOPIC, 1), (RESET_TOPIC, 1)])
    publish_status(cl)


def on_message(cl, userdata, msg):
    if msg.topic == TELE_TOPIC:
        handle_telem(cl, msg.payload)
    else:
        handle_command(cl, msg.topic, msg.payload)


client.on_connect = on_connect
client.on_message = on_message


def _graceful(*_):
    publish_status(client)  # snapshot before exit
    sys.exit(0)


signal.signal(signal.SIGTERM, _graceful)
signal.signal(signal.SIGINT, _graceful)

client.connect(BROKER_HOST, BROKER_PORT, keepalive=30)
client.loop_forever()
