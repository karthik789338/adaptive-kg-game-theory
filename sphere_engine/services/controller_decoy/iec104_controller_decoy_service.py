#!/usr/bin/env python3

import argparse
import json
import math
import signal
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import c104


COMMON_ADDRESS = 47
PORT = 2404

IOA_P_MEAS = 11
IOA_Q_MEAS = 12
IOA_VOLTAGE_MEAS = 13

IOA_P_COMMAND = 100
IOA_Q_COMMAND = 101

P_MAX_KW = 400.0
Q_MAX_KVAR = 300.0
S_MAX_KVA = 500.0

PLANT_URL = "http://10.40.0.20:8765"

NOMINAL_STATE = {
    "command_p_kw": 400.0,
    "command_q_kvar": 0.0,
    "p_injection_kw": 400.00338507478705,
    "q_injection_kvar": 0.002546371300089959,
    "bus675_mean_voltage_pu": 0.9992831675254893,
}

STATE_LOCK = threading.RLock()
STATE = dict(NOMINAL_STATE)

STOP_EVENT = threading.Event()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class Backend:

    def __init__(self, mode, event_log):

        self.mode = mode

        self.event_log = Path(event_log)

        self.event_log.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    def log(self, event, **fields):

        record = {
            "ts_utc": utc_now(),
            "event": event,
            "mode": self.mode,
            **fields,
        }

        with self.event_log.open(
            "a",
            encoding="ascii",
        ) as handle:

            handle.write(
                json.dumps(
                    record,
                    sort_keys=True,
                )
                + "\n"
            )

    def plant_request(
        self,
        path,
        payload=None,
    ):

        url = PLANT_URL + path

        if payload is None:

            request = urllib.request.Request(
                url,
                method="GET",
            )

        else:

            body = json.dumps(
                payload
            ).encode("utf-8")

            request = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Content-Type":
                        "application/json",
                    "X-Request-ID":
                        "iec104-"
                        + self.mode
                        + "-"
                        + str(
                            time.time_ns()
                        ),
                },
                method="POST",
            )

        with urllib.request.urlopen(
            request,
            timeout=5,
        ) as response:

            return json.load(
                response
            )

    def read_state(self):

        global STATE

        if self.mode == "real":

            response = self.plant_request(
                "/state"
            )

            state = response["state"]

            with STATE_LOCK:

                STATE = dict(state)

                return dict(STATE)

        with STATE_LOCK:

            return dict(STATE)

    def apply_command(
        self,
        p_kw,
        q_kvar,
    ):

        global STATE

        if not (
            0.0
            <= p_kw
            <= P_MAX_KW
        ):
            raise ValueError(
                "P outside allowed range"
            )

        if not (
            -Q_MAX_KVAR
            <= q_kvar
            <= Q_MAX_KVAR
        ):
            raise ValueError(
                "Q outside allowed range"
            )

        apparent = math.hypot(
            p_kw,
            q_kvar,
        )

        if apparent > (
            S_MAX_KVA
            + 1e-9
        ):
            raise ValueError(
                "Command exceeds "
                "500 kVA inverter rating"
            )

        if self.mode == "real":

            response = (
                self.plant_request(
                    "/command",
                    {
                        "enabled": True,
                        "p_kw": p_kw,
                        "q_kvar": q_kvar,
                    },
                )
            )

            state = response["state"]

        else:

            # ------------------------------------------------
            # Deterministic shadow response.
            #
            # Coefficients are derived from our already frozen
            # IEEE-13 smart-inverter validation results.
            #
            # This produces believable process feedback but
            # NEVER communicates with the real plant.
            # ------------------------------------------------

            base_voltage = (
                0.9939529864481482
            )

            p_voltage_gain = (
                (
                    0.9992831675254893
                    - base_voltage
                )
                / 400.0
            )

            q_voltage_gain = (
                (
                    1.0081993790101325
                    - 0.9923966962484867
                )
                / 600.0
            )

            voltage = (
                base_voltage
                + p_voltage_gain
                * p_kw
                + q_voltage_gain
                * q_kvar
            )

            state = {
                "command_p_kw":
                    p_kw,
                "command_q_kvar":
                    q_kvar,
                "p_injection_kw":
                    p_kw,
                "q_injection_kvar":
                    q_kvar,
                "bus675_mean_voltage_pu":
                    voltage,
            }

        with STATE_LOCK:

            STATE = dict(state)

            return dict(STATE)


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
        "--bind-ip",
        required=True,
    )

    parser.add_argument(
        "--event-log",
        required=True,
    )

    args = parser.parse_args()

    backend = Backend(
        mode=args.mode,
        event_log=args.event_log,
    )

    if args.mode == "real":

        initial = (
            backend.read_state()
        )

    else:

        initial = dict(
            NOMINAL_STATE
        )

    server = c104.Server(
        ip=args.bind_ip,
        port=PORT,
        tick_rate_ms=100,
        select_timeout_ms=10000,
        max_connections=8,
    )

    station = server.add_station(
        common_address=
            COMMON_ADDRESS
    )

    if station is None:
        raise RuntimeError(
            "Failed to create station"
        )

    # --------------------------------------------------------
    # Monitoring points
    # --------------------------------------------------------

    p_measurement = (
        station.add_point(
            io_address=
                IOA_P_MEAS,
            type=
                c104.Type.M_ME_NC_1,
            report_ms=1000,
        )
    )

    q_measurement = (
        station.add_point(
            io_address=
                IOA_Q_MEAS,
            type=
                c104.Type.M_ME_NC_1,
            report_ms=1000,
        )
    )

    voltage_measurement = (
        station.add_point(
            io_address=
                IOA_VOLTAGE_MEAS,
            type=
                c104.Type.M_ME_NC_1,
            report_ms=1000,
        )
    )

    # --------------------------------------------------------
    # Control points
    #
    # Select-before-execute deliberately matches the behavior
    # we later want for the Industroyer-inspired scenarios.
    # --------------------------------------------------------

    p_command = (
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

    q_command = (
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

    points = [
        p_measurement,
        q_measurement,
        voltage_measurement,
        p_command,
        q_command,
    ]

    if any(
        point is None
        for point in points
    ):
        raise RuntimeError(
            "Failed to create IEC-104 "
            "point map"
        )

    def update_measurements(
        state,
    ):

        p_measurement.value = (
            float(
                state[
                    "p_injection_kw"
                ]
            )
        )

        q_measurement.value = (
            float(
                state[
                    "q_injection_kvar"
                ]
            )
        )

        voltage_measurement.value = (
            float(
                state[
                    "bus675_mean_voltage_pu"
                ]
            )
        )

    update_measurements(
        initial
    )

    p_command.value = float(
        initial[
            "command_p_kw"
        ]
    )

    q_command.value = float(
        initial[
            "command_q_kvar"
        ]
    )

    # --------------------------------------------------------
    # Refresh monitoring data whenever SCADA interrogates.
    # --------------------------------------------------------

    def before_read(
        point: c104.Point,
    ) -> None:

        try:

            state = (
                backend.read_state()
            )

            update_measurements(
                state
            )

        except Exception as exc:

            backend.log(
                "measurement_refresh_failure",
                ioa=
                    point.io_address,
                detail=
                    str(exc),
            )

    for monitoring_point in [
        p_measurement,
        q_measurement,
        voltage_measurement,
    ]:

        monitoring_point.on_before_read(
            callable=before_read
        )

    def current_commands():

        with STATE_LOCK:

            return (
                float(
                    STATE[
                        "command_p_kw"
                    ]
                ),
                float(
                    STATE[
                        "command_q_kvar"
                    ]
                ),
            )

    # --------------------------------------------------------
    # P command callback.
    # SELECT validates only.
    # EXECUTE changes the backend.
    # --------------------------------------------------------

    def on_p_command(
        point: c104.Point,
        previous_info:
            c104.Information,
        message:
            c104.IncomingMessage,
    ) -> c104.ResponseState:

        requested = float(
            point.value
        )

        _, current_q = (
            current_commands()
        )

        if message.is_select_command:

            try:

                if not (
                    0.0
                    <= requested
                    <= P_MAX_KW
                ):
                    raise ValueError(
                        "P select out of range"
                    )

                if math.hypot(
                    requested,
                    current_q,
                ) > (
                    S_MAX_KVA
                    + 1e-9
                ):
                    raise ValueError(
                        "P select exceeds "
                        "inverter rating"
                    )

                backend.log(
                    "iec104_select",
                    ioa=
                        IOA_P_COMMAND,
                    quantity=
                        "p_kw",
                    requested=
                        requested,
                )

                return (
                    c104.ResponseState
                    .SUCCESS
                )

            except Exception as exc:

                backend.log(
                    "iec104_select_rejected",
                    ioa=
                        IOA_P_COMMAND,
                    detail=
                        str(exc),
                )

                return (
                    c104.ResponseState
                    .FAILURE
                )

        try:

            state = (
                backend.apply_command(
                    requested,
                    current_q,
                )
            )

            update_measurements(
                state
            )

            backend.log(
                "iec104_execute",
                ioa=
                    IOA_P_COMMAND,
                quantity=
                    "p_kw",
                requested=
                    requested,
                state=
                    state,
            )

            return (
                c104.ResponseState
                .SUCCESS
            )

        except Exception as exc:

            backend.log(
                "iec104_execute_rejected",
                ioa=
                    IOA_P_COMMAND,
                detail=
                    str(exc),
            )

            return (
                c104.ResponseState
                .FAILURE
            )

    # --------------------------------------------------------
    # Q command callback.
    # --------------------------------------------------------

    def on_q_command(
        point: c104.Point,
        previous_info:
            c104.Information,
        message:
            c104.IncomingMessage,
    ) -> c104.ResponseState:

        requested = float(
            point.value
        )

        current_p, _ = (
            current_commands()
        )

        if message.is_select_command:

            try:

                if not (
                    -Q_MAX_KVAR
                    <= requested
                    <= Q_MAX_KVAR
                ):
                    raise ValueError(
                        "Q select out of range"
                    )

                if math.hypot(
                    current_p,
                    requested,
                ) > (
                    S_MAX_KVA
                    + 1e-9
                ):
                    raise ValueError(
                        "Q select exceeds "
                        "inverter rating"
                    )

                backend.log(
                    "iec104_select",
                    ioa=
                        IOA_Q_COMMAND,
                    quantity=
                        "q_kvar",
                    requested=
                        requested,
                )

                return (
                    c104.ResponseState
                    .SUCCESS
                )

            except Exception as exc:

                backend.log(
                    "iec104_select_rejected",
                    ioa=
                        IOA_Q_COMMAND,
                    detail=
                        str(exc),
                )

                return (
                    c104.ResponseState
                    .FAILURE
                )

        try:

            state = (
                backend.apply_command(
                    current_p,
                    requested,
                )
            )

            update_measurements(
                state
            )

            backend.log(
                "iec104_execute",
                ioa=
                    IOA_Q_COMMAND,
                quantity=
                    "q_kvar",
                requested=
                    requested,
                state=
                    state,
            )

            return (
                c104.ResponseState
                .SUCCESS
            )

        except Exception as exc:

            backend.log(
                "iec104_execute_rejected",
                ioa=
                    IOA_Q_COMMAND,
                detail=
                    str(exc),
            )

            return (
                c104.ResponseState
                .FAILURE
            )

    p_command.on_receive(
        callable=on_p_command
    )

    q_command.on_receive(
        callable=on_q_command
    )

    def stop_handler(
        signum,
        frame,
    ):

        STOP_EVENT.set()

    signal.signal(
        signal.SIGTERM,
        stop_handler,
    )

    signal.signal(
        signal.SIGINT,
        stop_handler,
    )

    backend.log(
        "service_start",
        bind_ip=args.bind_ip,
        port=PORT,
        common_address=
            COMMON_ADDRESS,
        point_map={
            "p_measurement":
                IOA_P_MEAS,
            "q_measurement":
                IOA_Q_MEAS,
            "voltage_measurement":
                IOA_VOLTAGE_MEAS,
            "p_command":
                IOA_P_COMMAND,
            "q_command":
                IOA_Q_COMMAND,
        },
    )

    server.start()

    print(
        "IEC104_ENDPOINT_READY "
        f"mode={args.mode} "
        f"bind={args.bind_ip}:{PORT}",
        flush=True,
    )

    try:

        while not (
            STOP_EVENT.wait(1.0)
        ):
            pass

    finally:

        server.stop()

        backend.log(
            "service_stop"
        )


if __name__ == "__main__":
    main()
