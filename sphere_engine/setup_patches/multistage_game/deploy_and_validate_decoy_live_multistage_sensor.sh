#!/usr/bin/env bash

set -euo pipefail
set -o pipefail

SETUP="$HOME/ecpomdg_setup/multistage_game"
AUDIT="$HOME/ecpomdg_audit/multistage_game"

LOCAL_BUILD="$SETUP/live_multistage_sensor_build"

mkdir -p \
  "$LOCAL_BUILD" \
  "$AUDIT"


echo "================================================================"
echo " EC-POMDG DECOY LIVE MULTI-STAGE IEC-104 SENSOR"
echo "================================================================"


# ================================================================
# 1. SENSOR MODULE
# ================================================================

cat > \
"$LOCAL_BUILD/multistage_live_sensor.py" <<'PY'
import json
import struct
import threading

import c104

from datetime import datetime, timezone
from pathlib import Path


C_SE_NC_1 = 50
C_IC_NA_1 = 100
C_RD_NA_1 = 102

IOA_P_MEAS = 11
IOA_Q_MEAS = 12
IOA_VOLTAGE = 13

IOA_P_COMMAND = 100
IOA_Q_COMMAND = 101


WRITE_LOCK = threading.RLock()


def utc_now():

    return (
        datetime.now(
            timezone.utc
        )
        .isoformat()
    )


def endpoint_mode(
    server,
):

    ip = str(
        getattr(
            server,
            "ip",
            "",
        )
    )

    if ip == "10.30.0.10":
        return "real"

    if ip == "10.30.0.99":
        return "decoy"

    return "unknown"


def event_path(
    server,
):

    mode = endpoint_mode(
        server
    )

    path = (
        Path.home()
        / "ecpomdg"
        / "multistage_live"
        / "logs"
        / f"iec104_{mode}_multistage_sensor_events.jsonl"
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    return path


def append_event(
    server,
    event,
    **fields,
):

    record = {
        "ts_utc":
            utc_now(),

        "event":
            event,

        "protocol":
            "IEC104",

        "sensor":
            "server_raw_apdu",

        "mode":
            endpoint_mode(
                server
            ),

        **fields,
    }


    path = event_path(
        server
    )


    with WRITE_LOCK:

        with path.open(
            "a",
            encoding="ascii",
        ) as handle:

            handle.write(
                json.dumps(
                    record,
                    sort_keys=True,
                    ensure_ascii=True,
                )
                + "\n"
            )


def split_apdus(
    data,
):

    frames = []

    offset = 0


    while offset < len(data):

        if data[offset] != 0x68:

            offset += 1
            continue


        if (
            offset + 2
            > len(data)
        ):

            break


        length = data[
            offset + 1
        ]


        end = (
            offset
            + 2
            + length
        )


        if end > len(data):

            break


        frames.append(
            data[
                offset:end
            ]
        )


        offset = end


    return frames


def decode_relevant_apdu(
    apdu,
):

    if (
        len(apdu) < 6
        or
        apdu[0] != 0x68
    ):

        return None


    control0 = apdu[2]


    # ------------------------------------------------------------
    # U-format STARTDT
    # ------------------------------------------------------------

    if (
        control0
        & 0x03
    ) == 0x03:

        if control0 == 0x07:

            return {
                "event":
                    "iec104_session_established",

                "u_function":
                    "STARTDT_ACT",
            }


        return None


    # ------------------------------------------------------------
    # Ignore S-format
    # ------------------------------------------------------------

    if (
        control0
        & 0x03
    ) == 0x01:

        return None


    # ------------------------------------------------------------
    # I-format / ASDU
    # ------------------------------------------------------------

    if len(apdu) < 12:

        return None


    asdu = apdu[6:]


    if len(asdu) < 6:

        return None


    type_id = int(
        asdu[0]
    )

    cause = int(
        asdu[2]
        & 0x3F
    )

    common_address = int(
        asdu[4]
        |
        (
            asdu[5]
            << 8
        )
    )


    ioa = None


    if len(asdu) >= 9:

        ioa = int(
            asdu[6]
            |
            (
                asdu[7]
                << 8
            )
            |
            (
                asdu[8]
                << 16
            )
        )


    # ------------------------------------------------------------
    # General Interrogation
    # ------------------------------------------------------------

    if type_id == C_IC_NA_1:

        record = {
            "event":
                "iec104_interrogation",

            "asdu_type":
                C_IC_NA_1,

            "cause":
                cause,

            "common_address":
                common_address,
        }


        if len(asdu) >= 10:

            record[
                "qoi"
            ] = int(
                asdu[9]
            )


        return record


    # ------------------------------------------------------------
    # Explicit point read
    # ------------------------------------------------------------

    if type_id == C_RD_NA_1:

        return {
            "event":
                "iec104_point_read",

            "asdu_type":
                C_RD_NA_1,

            "cause":
                cause,

            "common_address":
                common_address,

            "ioa":
                ioa,
        }


    # ------------------------------------------------------------
    # C_SE_NC_1 SELECT / EXECUTE
    # ------------------------------------------------------------

    if (
        type_id == C_SE_NC_1
        and
        len(asdu) >= 14
    ):

        requested = float(
            struct.unpack(
                "<f",
                asdu[
                    9:13
                ],
            )[0]
        )


        qos = int(
            asdu[13]
        )


        is_select = bool(
            qos
            & 0x80
        )


        return {
            "event":
                (
                    "iec104_select"
                    if is_select
                    else
                    "iec104_execute_raw"
                ),

            "asdu_type":
                C_SE_NC_1,

            "cause":
                cause,

            "common_address":
                common_address,

            "ioa":
                ioa,

            "requested":
                requested,

            "command_phase":
                (
                    "select"
                    if is_select
                    else
                    "execute"
                ),
        }


    return None


def install_multistage_sensor(
    server,
):

    # ------------------------------------------------------------
    # No hidden-game information is available here.
    #
    # These callbacks see only live endpoint/network traffic.
    # ------------------------------------------------------------

    def on_connect(
        server: c104.Server,
        ip: str,
    ) -> bool:

        append_event(
            server,
            "iec104_connection_request",
            client_ip=
                str(ip),
        )

        # Preserve the endpoint's previous default behavior:
        # accept incoming IEC-104 clients.
        return True


    def on_receive_raw(
        server: c104.Server,
        data: bytes,
    ) -> None:

        try:

            for apdu in split_apdus(
                bytes(data)
            ):

                decoded = (
                    decode_relevant_apdu(
                        apdu
                    )
                )


                if decoded is None:
                    continue


                event = decoded.pop(
                    "event"
                )


                append_event(
                    server,
                    event,
                    **decoded,
                )


        except Exception as exc:

            append_event(
                server,
                "iec104_sensor_decode_error",
                detail=
                    str(exc),
            )


    server.on_connect(
        callable=on_connect
    )


    server.on_receive_raw(
        callable=on_receive_raw
    )
PY


# ================================================================
# 2. VERSIONED WRAPPER
#
# Loads the frozen endpoint implementation without changing it,
# replaces only c104.Server construction, and calls its existing main.
# ================================================================

cat > \
"$LOCAL_BUILD/iec104_controller_decoy_multistage_service.py" <<'PY'
#!/usr/bin/env python3

import importlib.util
from pathlib import Path

from multistage_live_sensor import (
    install_multistage_sensor,
)


ORIGINAL = (
    Path.home()
    / "ecpomdg"
    / "iec104_controller_decoy"
    / "app"
    / "iec104_controller_decoy_service.py"
)


spec = (
    importlib.util
    .spec_from_file_location(
        "frozen_iec104_controller_decoy_service",
        ORIGINAL,
    )
)


if (
    spec is None
    or
    spec.loader is None
):

    raise RuntimeError(
        "Unable to load frozen IEC-104 endpoint"
    )


legacy = (
    importlib.util
    .module_from_spec(
        spec
    )
)


spec.loader.exec_module(
    legacy
)


_original_server_constructor = (
    legacy.c104.Server
)


def instrumented_server(
    *args,
    **kwargs,
):

    server = (
        _original_server_constructor(
            *args,
            **kwargs,
        )
    )


    # FIX (callback-annotation poisoning): the patch below sets
    # c104.Server = instrumented_server on the SHARED c104 module, so the
    # sensor's callback annotations (server: c104.Server), evaluated at def
    # time, would resolve to this function and fail c104 2.2.1's signature
    # validation. Restore the real Server class now -- we already hold the
    # constructed server, and each endpoint builds exactly one server.
    legacy.c104.Server = _original_server_constructor


    install_multistage_sensor(
        server
    )


    return server


# The loaded legacy module gets the wrapper constructor.
# The frozen source file itself remains unchanged.
legacy.c104.Server = (
    instrumented_server
)


if __name__ == "__main__":

    legacy.main()
PY


# ================================================================
# 3. EARLY-STAGE TELEMETRY FORWARDER
# ================================================================

cat > \
"$LOCAL_BUILD/multistage_live_sensor_forwarder.py" <<'PY'
#!/usr/bin/env python3

import argparse
import json
import time
import urllib.request

from pathlib import Path


COLLECTOR_URL = (
    "http://10.45.0.30:9201/events"
)


FORWARDED_EVENTS = {
    "iec104_connection_request",
    "iec104_session_established",
    "iec104_interrogation",
    "iec104_point_read",
    "iec104_select",
}


def post_event(
    event,
):

    # ------------------------------------------------------------
    # Explicit outgoing whitelist.
    #
    # Do NOT forward:
    #   mode
    #   raw APDU
    #   hidden stage
    #   hidden target
    #   attacker profile
    #   redirect result
    #   future outcome
    # ------------------------------------------------------------

    payload = {
        "event":
            event[
                "event"
            ],

        "protocol":
            "IEC104",
    }


    for field in (
        "ioa",
        "requested",
        "asdu_type",
        "cause",
        "common_address",
        "command_phase",
        "qoi",
    ):

        if field in event:

            payload[
                field
            ] = event[
                field
            ]


    body = json.dumps(
        payload,
        sort_keys=True,
    ).encode(
        "utf-8"
    )


    request = urllib.request.Request(
        COLLECTOR_URL,
        data=
            body,

        headers={
            "Content-Type":
                "application/json",
        },

        method=
            "POST",
    )


    with urllib.request.urlopen(
        request,
        timeout=5,
    ) as response:

        if response.status != 200:

            raise RuntimeError(
                f"collector HTTP {response.status}"
            )


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--mode",
        choices=[
            "real",
            "decoy",
        ],
        required=True,
    )

    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=0.10,
    )

    args = parser.parse_args()


    source = (
        Path.home()
        / "ecpomdg"
        / "multistage_live"
        / "logs"
        / (
            "iec104_"
            + args.mode
            + "_multistage_sensor_events.jsonl"
        )
    )


    source.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    source.touch(
        exist_ok=True
    )


    print(
        "FOLLOWING:",
        source,
        flush=True,
    )


    with source.open(
        "r",
        encoding="ascii",
    ) as handle:

        # Start from new evidence only.
        handle.seek(
            0,
            2,
        )


        while True:

            position = (
                handle.tell()
            )

            line = (
                handle.readline()
            )


            if not line:

                handle.seek(
                    position
                )

                time.sleep(
                    args.poll_seconds
                )

                continue


            if not line.strip():

                continue


            try:

                event = json.loads(
                    line
                )


                if (
                    event.get(
                        "event"
                    )
                    not in
                    FORWARDED_EVENTS
                ):

                    continue


                post_event(
                    event
                )


                print(
                    "FORWARDED:",
                    event[
                        "event"
                    ],
                    event.get(
                        "ioa"
                    ),
                    flush=True,
                )


            except Exception as exc:

                print(
                    "FORWARD_ERROR:",
                    repr(exc),
                    flush=True,
                )

                time.sleep(
                    0.5
                )


if __name__ == "__main__":
    main()
PY


# ================================================================
# 4. SWITCH SCRIPT
# ================================================================

cat > \
"$LOCAL_BUILD/switch_decoy_to_multistage_service.py" <<'PY'
#!/usr/bin/env python3

import json
import os
import signal
import subprocess
import time

from pathlib import Path


HOME = Path.home()

ORIGINAL = (
    HOME
    / "ecpomdg"
    / "iec104_controller_decoy"
    / "app"
    / "iec104_controller_decoy_service.py"
)

WRAPPER = (
    HOME
    / "ecpomdg"
    / "multistage_live"
    / "app"
    / "iec104_controller_decoy_multistage_service.py"
)

PIDFILE = (
    HOME
    / "ecpomdg"
    / "iec104_controller_decoy"
    / "iec104_decoy_controller_service.pid"
)

AUDIT = (
    HOME
    / "ecpomdg"
    / "multistage_live"
    / "audit"
)

LOG = (
    HOME
    / "ecpomdg"
    / "multistage_live"
    / "logs"
    / "iec104_decoy_multistage_service.log"
)


AUDIT.mkdir(
    parents=True,
    exist_ok=True,
)

LOG.parent.mkdir(
    parents=True,
    exist_ok=True,
)


if not PIDFILE.exists():

    raise RuntimeError(
        f"Missing PID file: {PIDFILE}"
    )


old_pid = int(
    PIDFILE.read_text(
        encoding="ascii"
    ).strip()
)


cmdline_path = (
    Path("/proc")
    / str(old_pid)
    / "cmdline"
)


if not cmdline_path.exists():

    raise RuntimeError(
        f"Old decoy service PID {old_pid} is not running"
    )


raw = (
    cmdline_path
    .read_bytes()
)


old_args = [
    item.decode(
        "utf-8"
    )
    for item in raw.split(
        b"\x00"
    )
    if item
]


if not old_args:

    raise RuntimeError(
        "Unable to recover original service command"
    )


new_args = list(
    old_args
)


script_indices = [
    index
    for (
        index,
        value,
    )
    in enumerate(
        new_args
    )
    if value.endswith(
        "/iec104_controller_decoy_service.py"
    )
]


if len(script_indices) != 1:

    raise RuntimeError(
        "Could not uniquely identify endpoint script "
        f"in command: {old_args}"
    )


new_args[
    script_indices[0]
] = str(
    WRAPPER
)


(
    AUDIT
    / "decoy_original_service_command.json"
).write_text(
    json.dumps(
        {
            "pid":
                old_pid,

            "original_args":
                old_args,

            "multistage_args":
                new_args,
        },
        indent=2,
    )
    + "\n",
    encoding="ascii",
)


# ------------------------------------------------
# Stop current decoy endpoint.
# ------------------------------------------------

os.kill(
    old_pid,
    signal.SIGTERM,
)


deadline = (
    time.time()
    + 10
)


while (
    time.time()
    < deadline
):

    if not (
        Path("/proc")
        / str(old_pid)
    ).exists():

        break

    time.sleep(
        0.2
    )


if (
    Path("/proc")
    / str(old_pid)
).exists():

    os.kill(
        old_pid,
        signal.SIGKILL,
    )

    time.sleep(
        0.5
    )


def start(
    args,
    log_path,
):

    handle = log_path.open(
        "ab",
        buffering=0,
    )


    process = subprocess.Popen(
        args,
        stdin=
            subprocess.DEVNULL,

        stdout=
            handle,

        stderr=
            subprocess.STDOUT,

        start_new_session=
            True,
    )


    return process


# ------------------------------------------------
# Start versioned endpoint.
# ------------------------------------------------

process = start(
    new_args,
    LOG,
)


PIDFILE.write_text(
    str(
        process.pid
    )
    + "\n",
    encoding="ascii",
)


time.sleep(
    2.0
)


if process.poll() is not None:

    # --------------------------------------------
    # Automatic rollback.
    # --------------------------------------------

    rollback_log = (
        LOG.parent
        / "iec104_decoy_multistage_rollback.log"
    )


    rollback = start(
        old_args,
        rollback_log,
    )


    PIDFILE.write_text(
        str(
            rollback.pid
        )
        + "\n",
        encoding="ascii",
    )


    raise RuntimeError(
        "Versioned endpoint failed; "
        "original service automatically restored"
    )


print(
    "DECOY_MULTISTAGE_ENDPOINT_PID:",
    process.pid,
)

print(
    "ORIGINAL_SOURCE_UNCHANGED:",
    ORIGINAL,
)

print(
    "VERSIONED_WRAPPER:",
    WRAPPER,
)
PY


# ================================================================
# 5. LOCAL SOURCE CHECKS
# ================================================================

echo
echo "===== LOCAL SOURCE CHECKS ====="

python3 -m py_compile \
  "$LOCAL_BUILD/multistage_live_sensor.py" \
  "$LOCAL_BUILD/iec104_controller_decoy_multistage_service.py" \
  "$LOCAL_BUILD/multistage_live_sensor_forwarder.py" \
  "$LOCAL_BUILD/switch_decoy_to_multistage_service.py"


echo \
  "DECOY_MULTISTAGE_SENSOR_SOURCE_SYNTAX: PASS"


# ================================================================
# 6. COPY TO DECOY
# ================================================================

echo
echo "===== DEPLOY VERSIONED SENSOR FILES TO DECOY ====="

ssh decoy '
set -euo pipefail

mkdir -p \
  ~/ecpomdg/multistage_live/app \
  ~/ecpomdg/multistage_live/logs \
  ~/ecpomdg/multistage_live/audit
'


scp \
  "$LOCAL_BUILD/multistage_live_sensor.py" \
  "$LOCAL_BUILD/iec104_controller_decoy_multistage_service.py" \
  "$LOCAL_BUILD/multistage_live_sensor_forwarder.py" \
  "$LOCAL_BUILD/switch_decoy_to_multistage_service.py" \
  decoy:~/ecpomdg/multistage_live/app/


# ================================================================
# 7. VERIFY ORIGINAL SOURCE IS NOT MODIFIED
# ================================================================

echo
echo "===== VERIFY NO PRE-EXISTING RAW SERVER CALLBACKS ====="

ssh decoy '
set -euo pipefail

ORIGINAL="$HOME/ecpomdg/iec104_controller_decoy/app/iec104_controller_decoy_service.py"

if grep -q "\.on_connect(" "$ORIGINAL"
then
    echo "Existing on_connect callback found; refusing override."
    exit 81
fi

if grep -q "\.on_receive_raw(" "$ORIGINAL"
then
    echo "Existing on_receive_raw callback found; refusing override."
    exit 82
fi

sha256sum "$ORIGINAL" \
  > \
  "$HOME/ecpomdg/multistage_live/audit/frozen_decoy_endpoint_source_sha256.txt"

echo "FROZEN_DECOY_ENDPOINT_SOURCE_PRESERVED: PASS"
'


# ================================================================
# 8. SWITCH DECOY ONLY
# ================================================================

echo
echo "===== SWITCH DECOY TO VERSIONED SENSOR WRAPPER ====="

ssh decoy '
set -euo pipefail

"$HOME/ecpomdg/venvs/iec104/bin/python" \
  "$HOME/ecpomdg/multistage_live/app/switch_decoy_to_multistage_service.py"

sleep 1

ss -lntp \
  | grep "10.30.0.99:2404"

echo "DECOY_IEC104_PORT_2404_READY: PASS"
'


# ================================================================
# 9. START SENSOR FORWARDER
# ================================================================

echo
echo "===== START DECOY EARLY-STAGE FORWARDER ====="

ssh decoy '
set -euo pipefail

PIDFILE="$HOME/ecpomdg/multistage_live/decoy_multistage_sensor_forwarder.pid"
LOG="$HOME/ecpomdg/multistage_live/logs/decoy_multistage_sensor_forwarder.log"
APP="$HOME/ecpomdg/multistage_live/app/multistage_live_sensor_forwarder.py"

if test -f "$PIDFILE"
then
    OLD_PID="$(cat "$PIDFILE" || true)"

    if test -n "$OLD_PID" \
       && kill -0 "$OLD_PID" 2>/dev/null
    then
        kill "$OLD_PID"
        sleep 1
    fi
fi

nohup python3 \
    "$APP" \
    --mode decoy \
    >>"$LOG" \
    2>&1 \
    </dev/null &

echo $! > "$PIDFILE"

sleep 1

kill -0 "$(cat "$PIDFILE")"

echo "DECOY_MULTISTAGE_SENSOR_FORWARDER: PASS"
'


# ================================================================
# 10. BASELINE COUNTERS
# ================================================================

echo
echo "===== PRE-PROBE COUNTERS ====="

SENSOR_FILE='$HOME/ecpomdg/multistage_live/logs/iec104_decoy_multistage_sensor_events.jsonl'
OP_FILE='$HOME/ecpomdg/telemetry_ground_truth/logs/defender_operational_observation_events.jsonl'
PLANT_FILE='$HOME/ecpomdg/t2_gridsim/logs/plant_service_events.jsonl'


SENSOR0=$(
  ssh decoy "
      test -f \"$SENSOR_FILE\" \
      && wc -l < \"$SENSOR_FILE\" \
      || echo 0
  "
)

OP0=$(
  ssh collector "
      test -f \"$OP_FILE\" \
      && wc -l < \"$OP_FILE\" \
      || echo 0
  "
)

PLANT0=$(
  ssh gridsim "
      wc -l < \"$PLANT_FILE\"
  "
)


echo "sensor events:      $SENSOR0"
echo "operational events: $OP0"
echo "plant events:       $PLANT0"


# ================================================================
# 11. ACTIVE DECOY PROBE
# ================================================================

echo
echo "===== RUN DECOY P-CURTAIL PROBE ====="

ssh attacker '
set -euo pipefail

VENV="$HOME/ecpomdg/venvs/iec104_attack"
APP="$HOME/ecpomdg/industroyer_inspired_iec104/app/industroyer_inspired_iec104_emulator.py"

"$VENV/bin/python" \
  "$APP" \
  --target decoy \
  --scenario p_curtail
' \
| tee \
"$AUDIT/decoy_live_multistage_sensor_attack_probe.log"


sleep 3


# ================================================================
# 12. CAPTURE DELTAS
# ================================================================

echo
echo "===== CAPTURE LIVE SENSOR DELTAS ====="

ssh decoy "
    tail -n +$((SENSOR0 + 1)) \
      \"$SENSOR_FILE\"
" \
> \
"$AUDIT/decoy_live_multistage_sensor_events.jsonl"


ssh collector "
    test -f \"$OP_FILE\" \
    && tail -n +$((OP0 + 1)) \"$OP_FILE\" \
    || true
" \
> \
"$AUDIT/decoy_live_multistage_operational_events.jsonl"


ssh gridsim "
    tail -n +$((PLANT0 + 1)) \
      \"$PLANT_FILE\"
" \
> \
"$AUDIT/decoy_live_multistage_plant_events.jsonl"


# ================================================================
# 13. VALIDATE
# ================================================================

python3 - \
  "$AUDIT/decoy_live_multistage_sensor_events.jsonl" \
  "$AUDIT/decoy_live_multistage_operational_events.jsonl" \
  "$AUDIT/decoy_live_multistage_plant_events.jsonl" \
  "$AUDIT/decoy_live_multistage_sensor_validation.json" \
<<'PY'
import json
import sys

from collections import Counter
from pathlib import Path


(
    _,
    sensor_path,
    operational_path,
    plant_path,
    result_path,
) = sys.argv


def load_jsonl(
    path,
):

    rows = []

    path = Path(
        path
    )


    if not path.exists():

        return rows


    for line in path.read_text(
        encoding="utf-8"
    ).splitlines():

        if not line.strip():
            continue


        rows.append(
            json.loads(
                line
            )
        )


    return rows


sensor = load_jsonl(
    sensor_path
)

operational = load_jsonl(
    operational_path
)

plant = load_jsonl(
    plant_path
)


sensor_types = Counter(
    row.get(
        "event"
    )
    for row in sensor
)


operational_types = Counter(
    row.get(
        "event_type"
    )
    for row in operational
)


print()
print(
    "===== DECOY LOCAL SENSOR TYPES ====="
)

print(
    dict(
        sensor_types
    )
)


print()
print(
    "===== DECOY DEFENDER OPERATIONAL TYPES ====="
)

print(
    dict(
        operational_types
    )
)


# ------------------------------------------------
# Live local stage evidence
# ------------------------------------------------

assert (
    sensor_types[
        "iec104_connection_request"
    ]
    >= 1
)

print(
    "LIVE_CONNECTION_REQUEST_DETECTION: PASS"
)


assert (
    sensor_types[
        "iec104_session_established"
    ]
    >= 1
)

print(
    "LIVE_SESSION_ESTABLISHED_DETECTION: PASS"
)


assert (
    sensor_types[
        "iec104_interrogation"
    ]
    >= 1
)

print(
    "LIVE_INTERROGATION_DETECTION: PASS"
)


read_ioas = {
    int(
        row[
            "ioa"
        ]
    )
    for row in sensor
    if (
        row.get(
            "event"
        )
        == "iec104_point_read"
        and
        row.get(
            "ioa"
        )
        is not None
    )
}


assert {
    11,
    12,
    13,
}.issubset(
    read_ioas
)


print(
    "LIVE_DER_POINT_READ_SET_11_12_13: PASS"
)


select_rows = [
    row
    for row in sensor
    if (
        row.get(
            "event"
        )
        == "iec104_select"
    )
]


assert any(
    int(
        row.get(
            "ioa",
            -1,
        )
    )
    == 100

    for row
    in select_rows
)


print(
    "LIVE_RAW_CONTROL_SELECT_DETECTION: PASS"
)


raw_execute_rows = [
    row
    for row in sensor
    if (
        row.get(
            "event"
        )
        == "iec104_execute_raw"
    )
]


assert any(
    int(
        row.get(
            "ioa",
            -1,
        )
    )
    == 100

    for row
    in raw_execute_rows
)


print(
    "LIVE_RAW_EXECUTE_CORROBORATION: PASS"
)


# ------------------------------------------------
# Defender-visible propagation
# ------------------------------------------------

for expected in (
    "iec104_connection_request",
    "iec104_session_established",
    "iec104_interrogation",
    "iec104_point_read",
    "iec104_select",
    "iec104_execute",
):

    assert (
        operational_types[
            expected
        ]
        >= 1
    ), expected


print(
    "LIVE_EARLY_STAGE_DEFENDER_PROPAGATION: PASS"
)

print(
    "EXISTING_EXECUTE_DEFENDER_PROPAGATION: PASS"
)


operational_read_ioas = {
    int(
        row[
            "ioa"
        ]
    )
    for row in operational
    if (
        row.get(
            "event_type"
        )
        == "iec104_point_read"
        and
        row.get(
            "ioa"
        )
        is not None
    )
}


assert {
    11,
    12,
    13,
}.issubset(
    operational_read_ioas
)


print(
    "DEFENDER_DER_ENUMERATION_EVIDENCE: PASS"
)


assert any(
    row.get(
        "event_type"
    )
    == "iec104_select"
    and
    int(
        row.get(
            "ioa",
            -1,
        )
    )
    == 100

    for row
    in operational
)


print(
    "DEFENDER_CONTROL_SELECT_EVIDENCE: PASS"
)


# ------------------------------------------------
# Decoy physical isolation
# ------------------------------------------------

assert len(
    plant
) == 0


print(
    "DECOY_MULTISTAGE_PHYSICAL_ISOLATION: PASS"
)


# ------------------------------------------------
# Privacy
# ------------------------------------------------

forbidden = {
    "true_stage",
    "true_target",
    "attacker_profile",
    "redirect_success",
    "redirect_probability",
    "redirect_random_draw",
    "outcome",
}


serialized = json.dumps(
    operational,
    sort_keys=True,
)


for key in forbidden:

    assert (
        f'"{key}"'
        not in serialized
    )


print(
    "LIVE_MULTISTAGE_DEFENDER_ORACLE_LEAKAGE: NONE"
)


result = {
    "schema_version":
        1,

    "endpoint":
        "decoy",

    "sensor_event_count":
        len(
            sensor
        ),

    "operational_event_count":
        len(
            operational
        ),

    "plant_event_count":
        len(
            plant
        ),

    "sensor_event_types":
        dict(
            sensor_types
        ),

    "operational_event_types":
        dict(
            operational_types
        ),

    "measurement_read_ioas":
        sorted(
            read_ioas
        ),

    "physical_isolation":
        True,

    "oracle_leakage":
        False,
}


Path(
    result_path
).write_text(
    json.dumps(
        result,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="ascii",
)


print()
print(
    "DECOY_LIVE_MULTISTAGE_SENSOR_VALIDATION: PASS"
)
PY


# ================================================================
# 14. SHOW EVENTS
# ================================================================

echo
echo "===== LIVE SENSOR EVENTS ====="

cat \
  "$AUDIT/decoy_live_multistage_sensor_events.jsonl"


echo
echo "===== DEFENDER OPERATIONAL EVENTS ====="

cat \
  "$AUDIT/decoy_live_multistage_operational_events.jsonl"


# ================================================================
# 15. DEPLOYMENT HASHES
# ================================================================

echo
echo "===== FREEZE DECOY SENSOR VALIDATION ====="

sha256sum \
  "$LOCAL_BUILD/multistage_live_sensor.py" \
  "$LOCAL_BUILD/iec104_controller_decoy_multistage_service.py" \
  "$LOCAL_BUILD/multistage_live_sensor_forwarder.py" \
  "$LOCAL_BUILD/switch_decoy_to_multistage_service.py" \
  "$AUDIT/decoy_live_multistage_sensor_events.jsonl" \
  "$AUDIT/decoy_live_multistage_operational_events.jsonl" \
  "$AUDIT/decoy_live_multistage_plant_events.jsonl" \
  "$AUDIT/decoy_live_multistage_sensor_validation.json" \
  "$AUDIT/decoy_live_multistage_sensor_attack_probe.log" \
  > \
  "$AUDIT/decoy_live_multistage_sensor_sha256.txt"


ssh decoy '
sha256sum \
  ~/ecpomdg/iec104_controller_decoy/app/iec104_controller_decoy_service.py \
  ~/ecpomdg/multistage_live/app/multistage_live_sensor.py \
  ~/ecpomdg/multistage_live/app/iec104_controller_decoy_multistage_service.py \
  ~/ecpomdg/multistage_live/app/multistage_live_sensor_forwarder.py
' \
> \
"$AUDIT/decoy_live_multistage_deployed_sha256.txt"


cat \
  "$AUDIT/decoy_live_multistage_sensor_sha256.txt"


echo
echo "================================================================"
echo "DECOY_LIVE_MULTISTAGE_SENSOR: PASS"
echo "================================================================"

