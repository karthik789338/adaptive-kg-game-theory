#!/usr/bin/env python3

import json
import signal
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


BASE = (
    Path.home()
    / "ecpomdg"
    / "telemetry_ground_truth"
)

LOG_DIR = BASE / "logs"
RESULT_DIR = BASE / "results"

ORACLE_LOG = (
    LOG_DIR
    / "experiment_oracle_events.jsonl"
)

DEFENDER_LOG = (
    LOG_DIR
    / "defender_observation_events.jsonl"
)

SERVICE_LOG = (
    LOG_DIR
    / "telemetry_collector_service_events.jsonl"
)


# ----------------------------------------------------------------
# Interface separation
# ----------------------------------------------------------------

INGRESS_IP = "10.45.0.30"
INGRESS_PORT = 9201

DEFENDER_IP = "10.50.0.20"
DEFENDER_PORT = 9202


# ----------------------------------------------------------------
# Telemetry sources allowed to submit observations.
#
# Both real and decoy intentionally map to the SAME externally
# visible asset class.
# ----------------------------------------------------------------

INGRESS_SOURCES = {
    "10.30.0.10":
        "field_controller",

    "10.40.0.10":
        "field_controller",

    "10.30.0.99":
        "field_controller",

    "10.45.0.10":
        "scada",

    "127.0.0.1":
        "collector_local",

    "10.45.0.30":
        "collector_local",
}


# ----------------------------------------------------------------
# Only defender may consume the defender observation API.
# ----------------------------------------------------------------

DEFENDER_CLIENTS = {
    "10.50.0.40",
    "127.0.0.1",
    "10.50.0.20",
}


# ----------------------------------------------------------------
# These are observations legitimately reported by a controller.
#
# Explicit ground truth such as:
#
#   mode
#   source_ip
#   real/decoy label
#   physical_effect
#   ground_truth
#
# is NEVER copied into the defender stream.
# ----------------------------------------------------------------

# Attribution is from the TCP peer seen by the collector, NOT from
# untrusted raw_event fields such as mode, asset_id, or source_ip.
TRUSTED_SOURCE_ASSET_IDS = {
    "10.30.0.10": "asset-field-001",
    "10.40.0.10": "asset-field-001",
    "10.30.0.99": "asset-field-002",
    "10.45.0.10": "asset-scada-001",
    "127.0.0.1": "asset-collector-001",
    "10.45.0.30": "asset-collector-001",
}
OPERATIONAL_LOG = LOG_DIR / "defender_operational_observation_events.jsonl"

SAFE_STATE_FIELDS = {
    "command_p_kw",
    "command_q_kvar",
    "p_injection_kw",
    "q_injection_kvar",
    "bus675_mean_voltage_pu",

}


FILE_LOCK = threading.RLock()
OBSERVATION_LOCK = threading.RLock()

OBSERVATIONS = []
OPERATIONAL_OBSERVATIONS = []

STOP_EVENT = threading.Event()


def utc_now():

    return (
        datetime.now(
            timezone.utc
        )
        .isoformat()
    )


def append_jsonl(
    path,
    record,
):

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    line = (
        json.dumps(
            record,
            sort_keys=True,
            ensure_ascii=True,
        )
        + "\n"
    )

    with FILE_LOCK:

        with path.open(
            "a",
            encoding="ascii",
        ) as handle:

            handle.write(
                line
            )


def service_event(
    event,
    **fields,
):

    append_jsonl(
        SERVICE_LOG,
        {
            "ts_utc":
                utc_now(),
            "event":
                event,
            **fields,
        },
    )


def build_defender_observation(
    source_ip,
    raw_event,
    event_id,
    collector_ts,
):

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # Defender observations are constructed from an explicit
    # whitelist rather than by deleting sensitive fields.
    #
    # That prevents future event fields from accidentally
    # leaking ground truth.
    # --------------------------------------------------------

    observation = {
        "event_id":
            event_id,

        "collector_ts_utc":
            collector_ts,

        "asset_class":
            INGRESS_SOURCES[
                source_ip
            ],

        "protocol":
            raw_event.get(
                "protocol",
                "IEC104",
            ),

        "event_type":
            raw_event.get(
                "event",
                "unknown",
            ),
    }

    for field in (
        "ioa",
        "quantity",
        "requested",
        "accepted",
        "method",
        "path",
        "reason",
    ):

        if field in raw_event:

            observation[
                field
            ] = raw_event[
                field
            ]

    state = raw_event.get(
        "state"
    )

    if isinstance(
        state,
        dict,
    ):

        reported_state = {
            key:
                state[key]

            for key
            in SAFE_STATE_FIELDS

            if key in state
        }

        if reported_state:

            observation[
                "reported_state"
            ] = reported_state

    return observation


def build_operational_observation(source_ip, blind_record):
    # Deliberately no asset_role here: roles live only in the defender's
    # trusted registry. Keep the identity-blind stream untouched.
    asset_id = TRUSTED_SOURCE_ASSET_IDS[source_ip]
    record = dict(blind_record)
    record["asset_id"] = asset_id
    return record


def hydrate_observation_history():
    # Preserve older, already-frozen blind/oracle records without replaying
    # events to the collector or regenerating event IDs.
    oracle_sources = {}
    if ORACLE_LOG.exists():
        for line in ORACLE_LOG.read_text(encoding="ascii").splitlines():
            if line.strip():
                record = json.loads(line)
                oracle_sources[record["event_id"]] = record["source_ip"]

    blind_rows, operational_rows = [], []
    if DEFENDER_LOG.exists():
        for line in DEFENDER_LOG.read_text(encoding="ascii").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            source_ip = oracle_sources.get(row["event_id"])
            if source_ip is None:
                raise RuntimeError("Missing oracle pairing for defender event")
            blind_rows.append(row)
            operational_rows.append(
                build_operational_observation(source_ip, row)
            )

    with OBSERVATION_LOCK:
        OBSERVATIONS[:] = blind_rows[-10000:]
        OPERATIONAL_OBSERVATIONS[:] = operational_rows[-10000:]

    # Derived projection; always reconstruct from the canonical source logs.
    with OPERATIONAL_LOG.open("w", encoding="ascii") as output:
        for record in operational_rows:
            output.write(json.dumps(record, sort_keys=True, ensure_ascii=True) + "\n")
    OPERATIONAL_LOG.chmod(0o600)


def ingest_event(
    source_ip,
    payload,
):

    if not isinstance(
        payload,
        dict,
    ):
        raise ValueError(
            "payload must be a JSON object"
        )

    raw_event = payload.get(
        "event"
    )

    if not isinstance(
        raw_event,
        dict,
    ):
        raise ValueError(
            "payload.event must be a JSON object"
        )

    event_id = str(
        uuid.uuid4()
    )

    collector_ts = (
        utc_now()
    )

    # ========================================================
    # ORACLE COPY
    #
    # This retains everything.
    # The defender never receives this structure.
    # ========================================================

    oracle_record = {
        "event_id":
            event_id,

        "collector_ts_utc":
            collector_ts,

        "source_ip":
            source_ip,

        "source_asset_class":
            INGRESS_SOURCES[
                source_ip
            ],

        "raw_event":
            raw_event,
    }

    # ========================================================
    # DEFENDER COPY
    #
    # Strictly sanitized.
    # ========================================================

    defender_record = (
        build_defender_observation(
            source_ip,
            raw_event,
            event_id,
            collector_ts,
        )
    )

    append_jsonl(
        ORACLE_LOG,
        oracle_record,
    )

    append_jsonl(
        DEFENDER_LOG,
        defender_record,
    )
    operational_record = build_operational_observation(source_ip, defender_record)
    append_jsonl(OPERATIONAL_LOG, operational_record)

    with OBSERVATION_LOCK:

        OBSERVATIONS.append(
            defender_record
        )
        OPERATIONAL_OBSERVATIONS.append(operational_record)
        if len(OPERATIONAL_OBSERVATIONS) > 10000:
            del OPERATIONAL_OBSERVATIONS[:-10000]

        if (
            len(OBSERVATIONS)
            > 10000
        ):
            del OBSERVATIONS[
                :-10000
            ]

    return event_id


class JsonHandler(
    BaseHTTPRequestHandler
):

    server_version = (
        "ECPOMDGTelemetry/1.0"
    )

    def log_message(
        self,
        format,
        *args,
    ):
        return

    def send_json(
        self,
        status,
        payload,
    ):

        body = (
            json.dumps(
                payload,
                sort_keys=True,
                ensure_ascii=True,
            )
            + "\n"
        ).encode(
            "ascii"
        )

        self.send_response(
            status
        )

        self.send_header(
            "Content-Type",
            "application/json",
        )

        self.send_header(
            "Content-Length",
            str(len(body)),
        )

        self.send_header(
            "Cache-Control",
            "no-store",
        )

        self.end_headers()

        self.wfile.write(
            body
        )

    def read_json(
        self,
    ):

        length = int(
            self.headers.get(
                "Content-Length",
                "0",
            )
        )

        if (
            length <= 0
            or
            length > 1024 * 1024
        ):
            raise ValueError(
                "invalid request body length"
            )

        raw = self.rfile.read(
            length
        )

        return json.loads(
            raw.decode(
                "utf-8"
            )
        )


class IngressHandler(
    JsonHandler
):

    def authorized(
        self,
    ):

        return (
            self.client_address[0]
            in INGRESS_SOURCES
        )

    def do_GET(
        self,
    ):

        if not self.authorized():

            return self.send_json(
                403,
                {
                    "ok":
                        False,

                    "error":
                        "client_not_allowed",
                },
            )

        if self.path == "/health":

            return self.send_json(
                200,
                {
                    "ok":
                        True,

                    "service":
                        "ecpomdg-telemetry-ingress",

                    "bind_ip":
                        INGRESS_IP,

                    "port":
                        INGRESS_PORT,
                },
            )

        return self.send_json(
            404,
            {
                "ok":
                    False,

                "error":
                    "not_found",
            },
        )

    def do_POST(
        self,
    ):

        source_ip = (
            self.client_address[0]
        )

        if not self.authorized():

            service_event(
                "ingress_rejected",
                source_ip=
                    source_ip,

                reason=
                    "client_not_allowed",
            )

            return self.send_json(
                403,
                {
                    "ok":
                        False,

                    "error":
                        "client_not_allowed",
                },
            )

        if self.path != "/events":

            return self.send_json(
                404,
                {
                    "ok":
                        False,

                    "error":
                        "not_found",
                },
            )

        try:

            payload = (
                self.read_json()
            )

            event_id = (
                ingest_event(
                    source_ip,
                    payload,
                )
            )

            service_event(
                "ingress_accepted",
                source_ip=
                    source_ip,
                event_id=
                    event_id,
            )

            return self.send_json(
                200,
                {
                    "ok":
                        True,

                    "event_id":
                        event_id,
                },
            )

        except (
            ValueError,
            TypeError,
            json.JSONDecodeError,
        ) as exc:

            service_event(
                "ingress_bad_request",
                source_ip=
                    source_ip,
                detail=
                    str(exc),
            )

            return self.send_json(
                400,
                {
                    "ok":
                        False,

                    "error":
                        "bad_request",

                    "detail":
                        str(exc),
                },
            )


class DefenderHandler(
    JsonHandler
):

    def authorized(
        self,
    ):

        return (
            self.client_address[0]
            in DEFENDER_CLIENTS
        )

    def do_GET(
        self,
    ):

        source_ip = (
            self.client_address[0]
        )

        if not self.authorized():

            service_event(
                "defender_api_rejected",
                source_ip=
                    source_ip,
            )

            return self.send_json(
                403,
                {
                    "ok":
                        False,

                    "error":
                        "client_not_allowed",
                },
            )

        if self.path == "/health":

            return self.send_json(
                200,
                {
                    "ok":
                        True,

                    "service":
                        "ecpomdg-defender-observation-api",

                    "bind_ip":
                        DEFENDER_IP,

                    "port":
                        DEFENDER_PORT,
                },
            )

        if self.path.split("?", 1)[0] == "/operational-observations":
            with OBSERVATION_LOCK:
                operational = list(OPERATIONAL_OBSERVATIONS[-500:])
            return self.send_json(200, {
                "ok": True,
                "count": len(operational),
                "observations": operational,
            })

        if self.path.startswith(
            "/observations"
        ):

            with OBSERVATION_LOCK:

                observations = list(
                    OBSERVATIONS[
                        -500:
                    ]
                )

            return self.send_json(
                200,
                {
                    "ok":
                        True,

                    "count":
                        len(
                            observations
                        ),

                    "observations":
                        observations,
                },
            )

        return self.send_json(
            404,
            {
                "ok":
                    False,

                "error":
                    "not_found",
            },
        )


def main():

    LOG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    RESULT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    for path in (
        ORACLE_LOG,
        DEFENDER_LOG,
        SERVICE_LOG,
    ):

        path.touch(
            exist_ok=True
        )

        path.chmod(
            0o600
        )

    hydrate_observation_history()

    ingress_server = (
        ThreadingHTTPServer(
            (
                INGRESS_IP,
                INGRESS_PORT,
            ),
            IngressHandler,
        )
    )

    ingress_server.daemon_threads = (
        True
    )

    defender_server = (
        ThreadingHTTPServer(
            (
                DEFENDER_IP,
                DEFENDER_PORT,
            ),
            DefenderHandler,
        )
    )

    defender_server.daemon_threads = (
        True
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

    threads = [
        threading.Thread(
            target=
                ingress_server.serve_forever,

            name=
                "telemetry-ingress",

            daemon=True,
        ),

        threading.Thread(
            target=
                defender_server.serve_forever,

            name=
                "defender-observation-api",

            daemon=True,
        ),
    ]

    for thread in threads:

        thread.start()

    service_event(
        "service_start",

        ingress_ip=
            INGRESS_IP,

        ingress_port=
            INGRESS_PORT,

        defender_ip=
            DEFENDER_IP,

        defender_port=
            DEFENDER_PORT,
    )

    print(
        "=" * 68,
        flush=True,
    )

    print(
        " EC-POMDG TELEMETRY + GROUND-TRUTH COLLECTOR",
        flush=True,
    )

    print(
        "=" * 68,
        flush=True,
    )

    print(
        "Telemetry ingress: "
        f"http://{INGRESS_IP}:{INGRESS_PORT}/events",
        flush=True,
    )

    print(
        "Defender observations: "
        f"http://{DEFENDER_IP}:{DEFENDER_PORT}/observations",
        flush=True,
    )

    print(
        "Oracle exposure: LOCAL FILE ONLY",
        flush=True,
    )

    try:

        while not STOP_EVENT.wait(
            1.0
        ):
            pass

    finally:

        ingress_server.shutdown()
        defender_server.shutdown()

        ingress_server.server_close()
        defender_server.server_close()

        service_event(
            "service_stop"
        )


if __name__ == "__main__":
    main()
