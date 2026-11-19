#!/usr/bin/env python3

import argparse
import json
import time
import urllib.error
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


# Fields that are legitimate defender-visible protocol evidence.
SAFE_FIELDS = (
    "ioa",
    "requested",
    "asdu_type",
    "cause",
    "common_address",
    "command_phase",
    "qoi",
    "u_function",
)


def build_safe_event(
    source,
):

    event = {
        "event":
            source["event"],

        "protocol":
            "IEC104",
    }


    for field in SAFE_FIELDS:

        if field in source:

            event[
                field
            ] = source[
                field
            ]


    return event


def post_event(
    source_event,
):

    safe_event = (
        build_safe_event(
            source_event
        )
    )


    # ============================================================
    # IMPORTANT COLLECTOR CONTRACT
    #
    # /events expects:
    #
    # {
    #     "event": {
    #         ... actual controller event ...
    #     }
    # }
    #
    # It does NOT accept:
    #
    # {
    #     "event": "iec104_point_read",
    #     ...
    # }
    # ============================================================

    envelope = {
        "event":
            safe_event
    }


    body = json.dumps(
        envelope,
        sort_keys=True,
        ensure_ascii=True,
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


    try:

        with urllib.request.urlopen(
            request,
            timeout=5,
        ) as response:

            response_body = (
                response.read()
                .decode(
                    "utf-8"
                )
            )


            if response.status != 200:

                raise RuntimeError(
                    "collector returned "
                    f"HTTP {response.status}: "
                    f"{response_body}"
                )


            return json.loads(
                response_body
            )


    except urllib.error.HTTPError as exc:

        detail = (
            exc.read()
            .decode(
                "utf-8",
                errors="replace",
            )
        )


        raise RuntimeError(
            f"collector HTTP {exc.code}: "
            f"{detail}"
        ) from exc


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

        # Never replay old evidence when the forwarder restarts.
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

                source_event = (
                    json.loads(
                        line
                    )
                )


                event_name = (
                    source_event.get(
                        "event"
                    )
                )


                if (
                    event_name
                    not in
                    FORWARDED_EVENTS
                ):

                    continue


                response = post_event(
                    source_event
                )


                print(
                    "FORWARDED:",
                    event_name,
                    "ioa=",
                    source_event.get(
                        "ioa"
                    ),
                    "event_id=",
                    response.get(
                        "event_id"
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
