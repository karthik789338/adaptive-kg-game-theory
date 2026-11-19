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


def post_event(
    event,
):

    body = json.dumps(
        {
            "event":
                event
        }
    ).encode(
        "utf-8"
    )

    request = urllib.request.Request(
        COLLECTOR_URL,
        data=body,
        headers={
            "Content-Type":
                "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=5,
    ) as response:

        result = json.load(
            response
        )

    if not result.get(
        "ok"
    ):
        raise RuntimeError(
            f"collector rejected event: "
            f"{result}"
        )

    return result


def read_last_json(
    path,
):

    lines = [
        line
        for line
        in path.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]

    if not lines:
        raise RuntimeError(
            f"No events in {path}"
        )

    return json.loads(
        lines[-1]
    )


def send_last(
    path,
):

    event = read_last_json(
        path
    )

    result = post_event(
        event
    )

    print(
        "FORWARDED_LAST_EVENT:",
        result["event_id"],
        flush=True,
    )


def follow(
    path,
):

    with path.open(
        "r",
        encoding="utf-8",
    ) as handle:

        # Start at EOF so historical events are not
        # automatically replayed.
        handle.seek(
            0,
            2,
        )

        print(
            f"FOLLOWING: {path}",
            flush=True,
        )

        while True:

            line = handle.readline()

            if not line:

                time.sleep(
                    0.2
                )

                continue

            line = line.strip()

            if not line:
                continue

            try:

                event = json.loads(
                    line
                )

                result = post_event(
                    event
                )

                print(
                    "FORWARDED_EVENT:",
                    result[
                        "event_id"
                    ],
                    flush=True,
                )

            except Exception as exc:

                print(
                    "FORWARD_ERROR:",
                    type(exc).__name__,
                    str(exc),
                    flush=True,
                )


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--input-jsonl",
        required=True,
    )

    mode = (
        parser.add_mutually_exclusive_group(
            required=True
        )
    )

    mode.add_argument(
        "--send-last",
        action="store_true",
    )

    mode.add_argument(
        "--follow",
        action="store_true",
    )

    args = parser.parse_args()

    path = Path(
        args.input_jsonl
    )

    if not path.exists():

        raise SystemExit(
            f"Input log not found: {path}"
        )

    if args.send_last:

        send_last(
            path
        )

    else:

        follow(
            path
        )


if __name__ == "__main__":
    main()
