#!/usr/bin/env python3

import json
import socket
import struct
import time

from datetime import datetime, timezone
from pathlib import Path


# ============================================================
# EC-POMDG LAB-ONLY IEC-104 SELECT PROBE
#
# Intentionally fixed to the SPHERE decoy.
#
# It sends:
#   STARTDT_ACT
#   one C_SE_NC_1 SELECT for IOA 100, P=200 kW
#
# It NEVER sends an EXECUTE.
# ============================================================

TARGET_IP = "10.30.0.10"
TARGET_PORT = 2404

COMMON_ADDRESS = 47

TYPE_C_SE_NC_1 = 50
IOA_P_COMMAND = 100

COMMAND_VALUE = 200.0

COT_ACTIVATION = 6

SELECT_BIT = 0x80
QUALIFIER = 0

SOCKET_TIMEOUT_SECONDS = 2.0


RESULT_PATH = (
    Path.home()
    / "ecpomdg"
    / "industroyer_inspired_iec104"
    / "results"
    / "iec104_real_select_only_probe.json"
)


def utc_now():
    return (
        datetime.now(
            timezone.utc
        )
        .isoformat()
    )


def recv_exact(
    sock,
    length,
):
    data = bytearray()

    while len(data) < length:

        chunk = sock.recv(
            length - len(data)
        )

        if not chunk:
            raise ConnectionError(
                "connection closed while receiving APDU"
            )

        data.extend(
            chunk
        )

    return bytes(
        data
    )


def recv_apdu(
    sock,
):
    header = recv_exact(
        sock,
        2,
    )

    if header[0] != 0x68:
        raise RuntimeError(
            f"unexpected IEC-104 start byte: {header.hex()}"
        )

    length = header[1]

    payload = recv_exact(
        sock,
        length,
    )

    return (
        header
        +
        payload
    )


def build_u_frame(
    control_byte,
):
    return bytes([
        0x68,
        0x04,
        control_byte,
        0x00,
        0x00,
        0x00,
    ])


def build_s_frame(
    receive_sequence,
):
    encoded_nr = (
        int(
            receive_sequence
        )
        << 1
    )

    return (
        bytes([
            0x68,
            0x04,
            0x01,
            0x00,
        ])
        +
        struct.pack(
            "<H",
            encoded_nr,
        )
    )


def build_select_frame():
    # --------------------------------------------------------
    # APCI I-frame:
    #
    # N(S)=0
    # N(R)=0
    # --------------------------------------------------------

    control = (
        struct.pack(
            "<H",
            0,
        )
        +
        struct.pack(
            "<H",
            0,
        )
    )


    # --------------------------------------------------------
    # ASDU C_SE_NC_1
    #
    # Type: 50
    # VSQ:  1 information object
    # COT:  ACTIVATION
    # CA:   47
    # IOA:  100
    # value: 200.0 float32
    # QOS:
    #   bit 7 = SELECT
    #   bits 0..6 = qualifier 0
    # --------------------------------------------------------

    qos = (
        SELECT_BIT
        |
        QUALIFIER
    )


    asdu = (
        bytes([
            TYPE_C_SE_NC_1,
            0x01,
            COT_ACTIVATION,
            0x00,
        ])
        +
        struct.pack(
            "<H",
            COMMON_ADDRESS,
        )
        +
        bytes([
            IOA_P_COMMAND
            & 0xff,

            (
                IOA_P_COMMAND
                >> 8
            )
            & 0xff,

            (
                IOA_P_COMMAND
                >> 16
            )
            & 0xff,
        ])
        +
        struct.pack(
            "<f",
            COMMAND_VALUE,
        )
        +
        bytes([
            qos
        ])
    )


    apdu_length = (
        len(control)
        +
        len(asdu)
    )


    frame = (
        bytes([
            0x68,
            apdu_length,
        ])
        +
        control
        +
        asdu
    )


    return frame


def parse_i_frame(
    frame,
):
    if (
        len(frame) < 6
        or
        frame[0] != 0x68
    ):
        return None


    control0 = frame[2]


    if (
        control0
        &
        0x01
    ):
        return None


    ns_encoded = (
        frame[2]
        |
        (
            frame[3]
            << 8
        )
    )


    nr_encoded = (
        frame[4]
        |
        (
            frame[5]
            << 8
        )
    )


    result = {
        "send_sequence":
            (
                ns_encoded
                >> 1
            ),

        "receive_sequence":
            (
                nr_encoded
                >> 1
            ),
    }


    if len(frame) >= 15:

        result.update({
            "asdu_type":
                frame[6],

            "vsq":
                frame[7],

            "cause":
                (
                    frame[8]
                    &
                    0x3f
                ),

            "common_address":
                (
                    frame[10]
                    |
                    (
                        frame[11]
                        << 8
                    )
                ),
        })


    return result


def main():

    result = {
        "probe":
            "iec104_real_select_only",

        "started_ts_utc":
            utc_now(),

        "target_ip":
            TARGET_IP,

        "target_port":
            TARGET_PORT,

        "common_address":
            COMMON_ADDRESS,

        "ioa":
            IOA_P_COMMAND,

        "requested":
            COMMAND_VALUE,

        "select_only":
            True,

        "execute_sent":
            False,

        "received_apdus":
            [],
    }


    startdt_act = (
        build_u_frame(
            0x07
        )
    )


    select_frame = (
        build_select_frame()
    )


    # Last byte must be QOS with SELECT bit set.
    assert (
        select_frame[-1]
        &
        SELECT_BIT
    )


    assert (
        select_frame[-1]
        &
        0x7f
    ) == QUALIFIER


    result[
        "startdt_act_hex"
    ] = (
        startdt_act.hex()
    )


    result[
        "select_frame_hex"
    ] = (
        select_frame.hex()
    )


    result[
        "select_qos"
    ] = (
        select_frame[-1]
    )


    print(
        "TARGET:",
        f"{TARGET_IP}:{TARGET_PORT}",
    )

    print(
        "SELECT_FRAME:",
        select_frame.hex(),
    )

    print(
        "QOS:",
        hex(
            select_frame[-1]
        ),
    )


    with socket.create_connection(
        (
            TARGET_IP,
            TARGET_PORT,
        ),
        timeout=
            SOCKET_TIMEOUT_SECONDS,
    ) as sock:

        sock.settimeout(
            SOCKET_TIMEOUT_SECONDS
        )


        # ----------------------------------------------------
        # START DATA TRANSFER
        # ----------------------------------------------------

        sock.sendall(
            startdt_act
        )


        startdt_response = (
            recv_apdu(
                sock
            )
        )


        result[
            "startdt_response_hex"
        ] = (
            startdt_response.hex()
        )


        print(
            "STARTDT_RESPONSE:",
            startdt_response.hex(),
        )


        if (
            startdt_response
            !=
            build_u_frame(
                0x0b
            )
        ):

            raise RuntimeError(
                "STARTDT_CON not received"
            )


        # ----------------------------------------------------
        # SEND EXACTLY ONE SELECT.
        #
        # No EXECUTE is ever constructed or transmitted.
        # ----------------------------------------------------

        sock.sendall(
            select_frame
        )


        print(
            "SELECT_SENT: PASS"
        )


        deadline = (
            time.monotonic()
            +
            SOCKET_TIMEOUT_SECONDS
        )


        highest_server_sequence = (
            None
        )


        while (
            time.monotonic()
            <
            deadline
        ):

            try:

                frame = recv_apdu(
                    sock
                )

            except socket.timeout:

                break


            parsed = (
                parse_i_frame(
                    frame
                )
            )


            result[
                "received_apdus"
            ].append({
                "hex":
                    frame.hex(),

                "parsed":
                    parsed,
            })


            print(
                "RECEIVED:",
                frame.hex(),
            )


            if parsed is not None:

                sequence = (
                    parsed[
                        "send_sequence"
                    ]
                )


                if (
                    highest_server_sequence
                    is None
                    or
                    sequence
                    >
                    highest_server_sequence
                ):

                    highest_server_sequence = (
                        sequence
                    )


        # ----------------------------------------------------
        # Acknowledge any server I-frame we received.
        # ----------------------------------------------------

        if (
            highest_server_sequence
            is not None
        ):

            ack = (
                build_s_frame(
                    highest_server_sequence
                    +
                    1
                )
            )


            sock.sendall(
                ack
            )


            result[
                "s_frame_ack_hex"
            ] = (
                ack.hex()
            )


        # ----------------------------------------------------
        # Graceful STOPDT.
        # ----------------------------------------------------

        stopdt_act = (
            build_u_frame(
                0x13
            )
        )


        try:

            sock.sendall(
                stopdt_act
            )


            stopdt_response = (
                recv_apdu(
                    sock
                )
            )


            result[
                "stopdt_response_hex"
            ] = (
                stopdt_response.hex()
            )


        except (
            socket.timeout,
            ConnectionError,
            BrokenPipeError,
        ):

            result[
                "stopdt_response_hex"
            ] = None


    result[
        "finished_ts_utc"
    ] = utc_now()


    RESULT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    RESULT_PATH.write_text(
        json.dumps(
            result,
            indent=2,
            sort_keys=True,
        )
        +
        "\n",
        encoding="ascii",
    )


    print()
    print(
        "EXECUTE_SENT:",
        result[
            "execute_sent"
        ],
    )

    print(
        "RESULT:",
        RESULT_PATH,
    )

    print(
        "IEC104_REAL_SELECT_ONLY_PROBE: PASS"
    )


if __name__ == "__main__":
    main()
