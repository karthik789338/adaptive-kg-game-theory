#!/usr/bin/env bash

set -euo pipefail
set -o pipefail

SETUP="$HOME/ecpomdg_setup/kg_defender_integration"
AUDIT="$HOME/ecpomdg_audit/kg_defender_integration"

mkdir -p "$SETUP" "$AUDIT"

echo "================================================================"
echo " EC-POMDG LIVE KG-ENRICHED DEFENDER OBSERVATIONS"
echo "================================================================"


# ================================================================
# 1. CREATE READ-ONLY KG CONTEXT SERVICE
# ================================================================

echo
echo "===== CREATE KG CONTEXT SERVICE ====="

cat > "$SETUP/defender_knowledge_context_service.py" <<'PY'
#!/usr/bin/env python3

import json
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


INDEX_PATH = (
    Path.home()
    / "ecpomdg"
    / "kg_defender_integration"
    / "results"
    / "unified_defender_knowledge_index.json"
)

BIND_IP = "10.50.0.30"
PORT = 9301

ALLOWED_CLIENTS = {
    "10.50.0.40",   # defender
    "10.50.0.30",   # KG local
    "127.0.0.1",
}

FORBIDDEN_OBSERVATION_KEYS = {
    "raw_event",
    "ground_truth",
    "attack_success",
    "physical_effect",
    "source_ip",
    "mode",
}

STOP = threading.Event()


INDEX = json.loads(
    INDEX_PATH.read_text(
        encoding="ascii"
    )
)


def audit_input(value):

    if isinstance(value, dict):

        for key, child in value.items():

            if key in FORBIDDEN_OBSERVATION_KEYS:

                raise ValueError(
                    "forbidden observation field: "
                    + key
                )

            audit_input(child)

    elif isinstance(value, list):

        for child in value:
            audit_input(child)


def matches(rule, observation):

    for key, expected in rule[
        "match"
    ].items():

        if observation.get(
            key
        ) != expected:

            return False

    return True


def unique_by(items, key):

    result = {}
    for item in items:
        result[
            item.get(
                key,
                json.dumps(
                    item,
                    sort_keys=True,
                ),
            )
        ] = item

    return [
        result[k]
        for k in sorted(result)
    ]


def build_context(observation):

    audit_input(
        observation
    )

    asset_id = observation.get(
        "asset_id"
    )

    if not asset_id:

        raise ValueError(
            "asset_id is required"
        )

    asset_context = (
        INDEX[
            "trusted_asset_context"
        ].get(
            asset_id
        )
    )

    if asset_context is None:

        raise ValueError(
            f"unknown asset_id: {asset_id}"
        )

    matched = [
        rule
        for rule in INDEX[
            "observation_context_rules"
        ]
        if matches(
            rule,
            observation,
        )
    ]

    attack_context = []

    software_context = []

    for rule in matched:

        attack_context.extend(
            rule.get(
                "attack_context",
                [],
            )
        )

        software_context.extend(
            rule.get(
                "known_ics_software_context",
                [],
            )
        )

    attack_context = unique_by(
        attack_context,
        "technique_id",
    )

    software_context = unique_by(
        software_context,
        "external_id",
    )

    ioa = observation.get(
        "ioa"
    )

    control_point = (
        INDEX[
            "iec104_control_points"
        ].get(
            str(ioa),
            None,
        )
    )

    represented_components = []

    physical_components = []

    if control_point is not None:

        represented_components = list(
            INDEX[
                "smart_inverter_nodes"
            ]
        )

        if asset_context[
            "physical_grid_connected"
        ]:

            physical_components = list(
                INDEX[
                    "smart_inverter_nodes"
                ]
            )

    return {
        "asset_id":
            asset_id,

        "asset_context":
            asset_context,

        "knowledge_match":
            bool(matched),

        "matched_rule_ids": [
            rule[
                "rule_id"
            ]
            for rule in matched
        ],

        "control_point":
            control_point,

        "attack_context":
            attack_context,

        "known_ics_software_context":
            software_context,

        # A decoy can represent the same process object without
        # actually having a physical control path to it.
        "represented_component_context":
            represented_components,

        "physical_control_context":
            physical_components,

        "context_semantics":
            (
                "Knowledge context only; "
                "not an attack verdict."
            ),
    }


class Handler(
    BaseHTTPRequestHandler
):

    server_version = (
        "ECPOMDGKnowledgeContext/1.0"
    )

    def log_message(
        self,
        format,
        *args,
    ):
        return

    def authorized(self):

        return (
            self.client_address[0]
            in ALLOWED_CLIENTS
        )

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

    def read_json(self):

        length = int(
            self.headers.get(
                "Content-Length",
                "0",
            )
        )

        if (
            length <= 0
            or length > 1024 * 1024
        ):

            raise ValueError(
                "invalid request length"
            )

        return json.loads(
            self.rfile.read(
                length
            ).decode(
                "utf-8"
            )
        )

    def do_GET(self):

        if not self.authorized():

            return self.send_json(
                403,
                {
                    "ok": False,
                    "error":
                        "client_not_allowed",
                },
            )

        if self.path == "/health":

            return self.send_json(
                200,
                {
                    "ok": True,
                    "service":
                        "ecpomdg-defender-knowledge-context",
                    "index_schema_version":
                        INDEX["schema_version"],
                },
            )

        if self.path == "/summary":

            return self.send_json(
                200,
                {
                    "ok": True,
                    "source_graphs":
                        INDEX[
                            "source_graphs"
                        ],
                    "cross_graph_link_count":
                        len(
                            INDEX[
                                "cross_graph_links"
                            ]
                        ),
                    "observation_context_rule_count":
                        len(
                            INDEX[
                                "observation_context_rules"
                            ]
                        ),
                },
            )

        return self.send_json(
            404,
            {
                "ok": False,
                "error": "not_found",
            },
        )

    def do_POST(self):

        if not self.authorized():

            return self.send_json(
                403,
                {
                    "ok": False,
                    "error":
                        "client_not_allowed",
                },
            )

        if self.path != "/context":

            return self.send_json(
                404,
                {
                    "ok": False,
                    "error": "not_found",
                },
            )

        try:

            observation = (
                self.read_json()
            )

            context = build_context(
                observation
            )

            return self.send_json(
                200,
                {
                    "ok": True,
                    "context":
                        context,
                },
            )

        except (
            ValueError,
            TypeError,
            KeyError,
            json.JSONDecodeError,
        ) as exc:

            return self.send_json(
                400,
                {
                    "ok": False,
                    "error":
                        "invalid_observation",
                    "detail":
                        str(exc),
                },
            )


def main():

    server = (
        ThreadingHTTPServer(
            (
                BIND_IP,
                PORT,
            ),
            Handler,
        )
    )

    server.daemon_threads = True

    def stop_handler(
        signum,
        frame,
    ):
        STOP.set()

    signal.signal(
        signal.SIGTERM,
        stop_handler,
    )

    signal.signal(
        signal.SIGINT,
        stop_handler,
    )

    thread = threading.Thread(
        target=
            server.serve_forever,
        daemon=True,
    )

    thread.start()

    print(
        "KG_CONTEXT_SERVICE_READY "
        f"{BIND_IP}:{PORT}",
        flush=True,
    )

    try:

        while not STOP.wait(
            1
        ):
            pass

    finally:

        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
PY


cat > "$SETUP/start_defender_knowledge_context_service.sh" <<'SH'
#!/usr/bin/env bash

set -euo pipefail

BASE="$HOME/ecpomdg/kg_defender_integration"

PIDFILE="$BASE/defender_knowledge_context_service.pid"

LOG="$BASE/results/defender_knowledge_context_service.log"

mkdir -p "$BASE/results"

if [ -f "$PIDFILE" ]; then

    PID="$(cat "$PIDFILE")"

    if kill -0 "$PID" 2>/dev/null
    then
        echo \
          "Knowledge context service already running: $PID"

        exit 0
    fi

    rm -f "$PIDFILE"
fi


nohup env \
  PYTHONIOENCODING=UTF-8 \
  python3 \
  "$BASE/app/defender_knowledge_context_service.py" \
  > "$LOG" \
  2>&1 &

PID=$!

echo "$PID" > "$PIDFILE"

sleep 2

if ! kill -0 "$PID" 2>/dev/null
then

    echo \
      "Knowledge context service failed."

    cat "$LOG"

    exit 1
fi

echo \
  "Knowledge context service started."

echo \
  "PID: $PID"
SH


cat > "$SETUP/stop_defender_knowledge_context_service.sh" <<'SH'
#!/usr/bin/env bash

set -euo pipefail

BASE="$HOME/ecpomdg/kg_defender_integration"

PIDFILE="$BASE/defender_knowledge_context_service.pid"

if [ ! -f "$PIDFILE" ]; then
    exit 0
fi

PID="$(cat "$PIDFILE")"

if kill -0 "$PID" 2>/dev/null
then
    kill "$PID"
fi

rm -f "$PIDFILE"

echo \
  "Knowledge context service stopped."
SH


chmod 755 \
  "$SETUP/start_defender_knowledge_context_service.sh" \
  "$SETUP/stop_defender_knowledge_context_service.sh"


# ================================================================
# 2. CREATE DEFENDER ENRICHMENT CLIENT
# ================================================================

echo
echo "===== CREATE DEFENDER KG ENRICHMENT CLIENT ====="

cat > "$SETUP/defender_kg_enriched_observation_client.py" <<'PY'
#!/usr/bin/env python3

import json
import os
import urllib.request
from collections import Counter
from pathlib import Path


BASE = (
    Path.home()
    / "ecpomdg"
    / "kg_defender_integration"
)

TELEMETRY_BASE = (
    Path.home()
    / "ecpomdg"
    / "telemetry_ground_truth"
)

REGISTRY_PATH = (
    TELEMETRY_BASE
    / "config"
    / "defender_trusted_asset_registry.json"
)

OUTPUT = (
    BASE
    / "results"
    / "defender_kg_enriched_observations_snapshot.json"
)

VECTOR_OUTPUT = (
    BASE
    / "results"
    / "defender_kg_enriched_observation_vectors.jsonl"
)

COLLECTOR_URL = (
    "http://10.50.0.20:9202"
    "/operational-observations"
)

KG_CONTEXT_URL = (
    "http://10.50.0.30:9301/context"
)


FORBIDDEN_KEYS = {
    "raw_event",
    "source_ip",
    "mode",
    "ground_truth",
    "attack_success",
    "physical_effect",
}


VECTOR_SCHEMA = [
    "asset_role_real",
    "asset_role_decoy",
    "physical_grid_connected",
    "protocol_iec104",
    "event_iec104_execute",
    "ioa_active_power",
    "ioa_reactive_power",
    "attack_context_T0831",
    "attack_context_T0836",
    "attack_context_T1692_001",
    "requested_value",
    "reported_p_kw",
    "reported_q_kvar",
    "reported_voltage_pu",
    "kg_rule_match_count"
]


def fetch_json(url):

    with urllib.request.urlopen(
        url,
        timeout=8,
    ) as response:

        return json.load(
            response
        )


def post_json(
    url,
    payload,
):

    request = urllib.request.Request(
        url,
        data=json.dumps(
            payload
        ).encode(
            "utf-8"
        ),
        headers={
            "Content-Type":
                "application/json"
        },
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=8,
    ) as response:

        return json.load(
            response
        )


def audit_no_oracle(value):

    if isinstance(value, dict):

        for key, child in value.items():

            assert key not in FORBIDDEN_KEYS, (
                f"Forbidden field in enriched view: {key}"
            )

            audit_no_oracle(
                child
            )

    elif isinstance(value, list):

        for child in value:

            audit_no_oracle(
                child
            )


registry = json.loads(
    REGISTRY_PATH.read_text(
        encoding="utf-8"
    )
)[
    "assets"
]


payload = fetch_json(
    COLLECTOR_URL
)

assert payload[
    "ok"
] is True

observations = payload[
    "observations"
]

assert observations


enriched_rows = []

vector_rows = []


for observation in observations:

    asset_id = observation[
        "asset_id"
    ]

    assert asset_id in registry, (
        f"Unknown defender asset: {asset_id}"
    )

    trusted = registry[
        asset_id
    ]

    response = post_json(
        KG_CONTEXT_URL,
        observation,
    )

    assert response[
        "ok"
    ] is True

    context = response[
        "context"
    ]


    # ------------------------------------------------------------
    # Verify KG asset context agrees with defender-owned registry.
    # ------------------------------------------------------------

    expected_kg_role = {
        "real":
            "real_controller",

        "decoy":
            "decoy_controller",

        "scada":
            "scada_master",

        "collector":
            "telemetry_collector",
    }.get(
        trusted[
            "asset_role"
        ]
    )

    if expected_kg_role is not None:

        assert (
            context[
                "asset_context"
            ][
                "role"
            ]
            == expected_kg_role
        )


    assert (
        context[
            "asset_context"
        ][
            "physical_grid_connected"
        ]
        == trusted[
            "physical_grid_connected"
        ]
    )


    techniques = {
        row[
            "technique_id"
        ]
        for row in context[
            "attack_context"
        ]
    }


    state = observation.get(
        "reported_state",
        {}
    )


    enriched = {
        "event_id":
            observation[
                "event_id"
            ],

        "collector_ts_utc":
            observation[
                "collector_ts_utc"
            ],

        "asset_id":
            asset_id,

        "asset_role":
            trusted[
                "asset_role"
            ],

        "physical_grid_connected":
            trusted[
                "physical_grid_connected"
            ],

        "protocol":
            observation.get(
                "protocol"
            ),

        "event_type":
            observation.get(
                "event_type"
            ),

        "ioa":
            observation.get(
                "ioa"
            ),

        "quantity":
            observation.get(
                "quantity"
            ),

        "requested":
            observation.get(
                "requested"
            ),

        "reported_state":
            state,

        "kg_context": {
            "knowledge_match":
                context[
                    "knowledge_match"
                ],

            "matched_rule_ids":
                context[
                    "matched_rule_ids"
                ],

            "control_point":
                context[
                    "control_point"
                ],

            "attack_context":
                context[
                    "attack_context"
                ],

            "known_ics_software_context":
                context[
                    "known_ics_software_context"
                ],

            "represented_component_context":
                context[
                    "represented_component_context"
                ],

            "physical_control_context":
                context[
                    "physical_control_context"
                ],

            "context_semantics":
                context[
                    "context_semantics"
                ],
        },
    }


    vector = [
        1
        if trusted[
            "asset_role"
        ] == "real"
        else 0,

        1
        if trusted[
            "asset_role"
        ] == "decoy"
        else 0,

        1
        if trusted[
            "physical_grid_connected"
        ]
        else 0,

        1
        if observation.get(
            "protocol"
        ) == "IEC104"
        else 0,

        1
        if observation.get(
            "event_type"
        ) == "iec104_execute"
        else 0,

        1
        if observation.get(
            "ioa"
        ) == 100
        else 0,

        1
        if observation.get(
            "ioa"
        ) == 101
        else 0,

        1
        if "T0831"
        in techniques
        else 0,

        1
        if "T0836"
        in techniques
        else 0,

        1
        if "T1692.001"
        in techniques
        else 0,

        float(
            observation.get(
                "requested",
                0.0,
            )
        ),

        float(
            state.get(
                "p_injection_kw",
                0.0,
            )
        ),

        float(
            state.get(
                "q_injection_kvar",
                0.0,
            )
        ),

        float(
            state.get(
                "bus675_mean_voltage_pu",
                0.0,
            )
        ),

        len(
            context[
                "matched_rule_ids"
            ]
        ),
    ]


    assert len(vector) == len(
        VECTOR_SCHEMA
    )


    enriched_rows.append(
        enriched
    )

    vector_rows.append({
        "event_id":
            observation[
                "event_id"
            ],

        "schema":
            VECTOR_SCHEMA,

        "vector":
            vector,
    })


# ================================================================
# VALIDATION
# ================================================================

audit_no_oracle(
    enriched_rows
)


roles = Counter(
    row[
        "asset_role"
    ]
    for row in enriched_rows
)


assert roles[
    "real"
] > 0

assert roles[
    "decoy"
] > 0


matched = [
    row
    for row in enriched_rows
    if row[
        "kg_context"
    ][
        "knowledge_match"
    ]
]


assert matched


for row in matched:

    techniques = {
        item[
            "technique_id"
        ]
        for item in row[
            "kg_context"
        ][
            "attack_context"
        ]
    }

    assert {
        "T0831",
        "T0836",
        "T1692.001",
    }.issubset(
        techniques
    )

    assert "T0806" not in techniques


# Real controller has a physical component context.
real_rows = [
    row
    for row in enriched_rows
    if row[
        "asset_role"
    ] == "real"
]


for row in real_rows:

    if row[
        "kg_context"
    ][
        "control_point"
    ] is not None:

        assert row[
            "kg_context"
        ][
            "physical_control_context"
        ]


# Decoy represents the same control object but has no physical path.
decoy_rows = [
    row
    for row in enriched_rows
    if row[
        "asset_role"
    ] == "decoy"
]


for row in decoy_rows:

    if row[
        "kg_context"
    ][
        "control_point"
    ] is not None:

        assert row[
            "kg_context"
        ][
            "represented_component_context"
        ]

        assert not row[
            "kg_context"
        ][
            "physical_control_context"
        ]


OUTPUT.parent.mkdir(
    parents=True,
    exist_ok=True,
)


OUTPUT.write_text(
    json.dumps(
        {
            "schema_version":
                1,

            "vector_schema":
                VECTOR_SCHEMA,

            "observation_count":
                len(
                    enriched_rows
                ),

            "role_counts":
                dict(
                    roles
                ),

            "observations":
                enriched_rows,
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="ascii",
)


with VECTOR_OUTPUT.open(
    "w",
    encoding="ascii",
) as handle:

    for row in vector_rows:

        handle.write(
            json.dumps(
                row,
                sort_keys=True,
                ensure_ascii=True,
            )
            + "\n"
        )


os.chmod(
    OUTPUT,
    0o600,
)

os.chmod(
    VECTOR_OUTPUT,
    0o600,
)


print(
    "KG_ENRICHED_OBSERVATION_FETCH: PASS"
)

print(
    "DEFENDER_TRUSTED_ROLE_JOIN: PASS"
)

print(
    "KG_ATTACK_CONTEXT_JOIN: PASS"
)

print(
    "REAL_PHYSICAL_COMPONENT_CONTEXT: PASS"
)

print(
    "DECOY_NO_PHYSICAL_COMPONENT_CONTROL: PASS"
)

print(
    "ORACLE_GROUND_TRUTH_LEAKAGE: NONE"
)

print(
    "NO_FALSE_BRUTE_FORCE_IO_CONTEXT: PASS"
)

print(
    "KG_ENRICHED_VECTOR_GENERATION: PASS"
)

print(
    "Observation count:",
    len(
        enriched_rows
    )
)

print(
    "Role counts:",
    dict(
        roles
    )
)

print(
    "Vector dimension:",
    len(
        VECTOR_SCHEMA
    )
)

print(
    "Snapshot:",
    OUTPUT
)

print(
    "Vectors:",
    VECTOR_OUTPUT
)
PY


# ================================================================
# 3. SYNTAX CHECK EVERYTHING BEFORE DEPLOYMENT
# ================================================================

echo
echo "===== LOCAL SYNTAX VALIDATION ====="

python3 -m py_compile \
  "$SETUP/defender_knowledge_context_service.py"

python3 -m py_compile \
  "$SETUP/defender_kg_enriched_observation_client.py"

bash -n \
  "$SETUP/start_defender_knowledge_context_service.sh"

bash -n \
  "$SETUP/stop_defender_knowledge_context_service.sh"

echo \
  "LIVE_KG_INTEGRATION_SOURCE_SYNTAX: PASS"


# ================================================================
# 4. VERIFY UNIFIED INDEX BEFORE SERVICE START
# ================================================================

echo
echo "===== VERIFY FROZEN UNIFIED INDEX ====="

ssh kg '
set -euo pipefail

BASE="$HOME/ecpomdg/kg_defender_integration"

cd /

sha256sum \
  -c \
  "$BASE/audit/unified_defender_knowledge_index_sha256.txt"
'

echo \
  "UNIFIED_INDEX_INTEGRITY: PASS"


# ================================================================
# 5. DEPLOY KG SERVICE
# ================================================================

echo
echo "===== DEPLOY KG CONTEXT SERVICE ====="

scp \
  "$SETUP/defender_knowledge_context_service.py" \
  kg:~/ecpomdg/kg_defender_integration/app/

scp \
  "$SETUP/start_defender_knowledge_context_service.sh" \
  kg:~/ecpomdg/kg_defender_integration/app/

scp \
  "$SETUP/stop_defender_knowledge_context_service.sh" \
  kg:~/ecpomdg/kg_defender_integration/app/


ssh kg '
set -euo pipefail

chmod 755 \
  ~/ecpomdg/kg_defender_integration/app/*.sh

python3 \
  -m py_compile \
  ~/ecpomdg/kg_defender_integration/app/defender_knowledge_context_service.py

~/ecpomdg/kg_defender_integration/app/stop_defender_knowledge_context_service.sh \
  || true

~/ecpomdg/kg_defender_integration/app/start_defender_knowledge_context_service.sh

echo

ss -lntp \
  | grep ":9301"

echo

cat \
  ~/ecpomdg/kg_defender_integration/results/defender_knowledge_context_service.log
'


# ================================================================
# 6. DEPLOY DEFENDER CLIENT
# ================================================================

echo
echo "===== DEPLOY DEFENDER ENRICHMENT CLIENT ====="

ssh defender '
mkdir -p \
  ~/ecpomdg/kg_defender_integration/app \
  ~/ecpomdg/kg_defender_integration/results
'


scp \
  "$SETUP/defender_kg_enriched_observation_client.py" \
  defender:~/ecpomdg/kg_defender_integration/app/


ssh defender '
python3 \
  -m py_compile \
  ~/ecpomdg/kg_defender_integration/app/defender_kg_enriched_observation_client.py
'


# ================================================================
# 7. DEFENDER -> KG SERVICE HEALTH
# ================================================================

echo
echo "===== DEFENDER -> KG CONTEXT HEALTH ====="

ssh defender python3 - <<'PY'
import json
import urllib.request

base = "http://10.50.0.30:9301"

with urllib.request.urlopen(
    base + "/health",
    timeout=5,
) as response:

    health = json.load(
        response
    )

with urllib.request.urlopen(
    base + "/summary",
    timeout=5,
) as response:

    summary = json.load(
        response
    )


assert health["ok"] is True

assert summary["ok"] is True

assert (
    summary[
        "observation_context_rule_count"
    ]
    == 2
)

assert (
    summary[
        "cross_graph_link_count"
    ]
    == 72
)


print(
    "DEFENDER_KG_CONTEXT_HEALTH: PASS"
)

print(
    "cross graph links:",
    summary[
        "cross_graph_link_count"
    ]
)

print(
    "context rules:",
    summary[
        "observation_context_rule_count"
    ]
)
PY


# ================================================================
# 8. UNAUTHORIZED KG SERVICE ACCESS
# ================================================================

echo
echo "===== UNAUTHORIZED KG CONTEXT ACCESS ====="

for node in attacker controller decoy
do

    echo "--- $node ---"

    ssh "$node" python3 - <<'PY'
import urllib.error
import urllib.request

url = (
    "http://10.50.0.30:9301/health"
)

try:

    with urllib.request.urlopen(
        url,
        timeout=3,
    ) as response:

        raise SystemExit(
            "FAIL: unauthorized KG access "
            f"HTTP {response.status}"
        )

except urllib.error.HTTPError as exc:

    assert exc.code == 403

    print(
        "KG_CONTEXT_UNAUTHORIZED_ACCESS: DENIED_403"
    )

except urllib.error.URLError as exc:

    print(
        "KG_CONTEXT_UNAUTHORIZED_ACCESS: NETWORK_BLOCKED"
    )

    print(
        str(
            exc.reason
        )
    )
PY

done


# ================================================================
# 9. RECORD CURRENT TELEMETRY COUNT
# ================================================================

echo
echo "===== LIVE TELEMETRY BASELINE ====="

EVENTS_BEFORE="$(
  ssh collector \
  'test -f ~/ecpomdg/telemetry_ground_truth/logs/defender_operational_observation_events.jsonl && wc -l < ~/ecpomdg/telemetry_ground_truth/logs/defender_operational_observation_events.jsonl || echo 0'
)"

echo \
  "operational events before: $EVENTS_BEFORE"


# ================================================================
# 10. GENERATE ONE BOUNDED REAL + DECOY SEQUENCE
# ================================================================

echo
echo "===== GENERATE REAL CONTROLLER LIVE OBSERVATIONS ====="

ssh attacker '
set -euo pipefail

VENV="$HOME/ecpomdg/venvs/iec104_attack"
BASE="$HOME/ecpomdg/industroyer_inspired_iec104"

"$VENV/bin/python" \
  "$BASE/app/industroyer_inspired_iec104_emulator.py" \
  --target real \
  --scenario p_curtail
' \
| tee \
"$AUDIT/kg_integration_real_live_probe.log"


echo
echo "===== GENERATE DECOY CONTROLLER LIVE OBSERVATIONS ====="

ssh attacker '
set -euo pipefail

VENV="$HOME/ecpomdg/venvs/iec104_attack"
BASE="$HOME/ecpomdg/industroyer_inspired_iec104"

"$VENV/bin/python" \
  "$BASE/app/industroyer_inspired_iec104_emulator.py" \
  --target decoy \
  --scenario p_curtail
' \
| tee \
"$AUDIT/kg_integration_decoy_live_probe.log"


sleep 3


EVENTS_AFTER="$(
  ssh collector \
  'test -f ~/ecpomdg/telemetry_ground_truth/logs/defender_operational_observation_events.jsonl && wc -l < ~/ecpomdg/telemetry_ground_truth/logs/defender_operational_observation_events.jsonl || echo 0'
)"

EVENT_DELTA=$((EVENTS_AFTER - EVENTS_BEFORE))

echo
echo \
  "operational events after: $EVENTS_AFTER"

echo \
  "operational event delta:  $EVENT_DELTA"

test \
  "$EVENT_DELTA" \
  -ge 4

echo \
  "LIVE_OPERATIONAL_TELEMETRY_FOR_KG: PASS"


# ================================================================
# 11. RUN DEFENDER ENRICHMENT
# ================================================================

echo
echo "===== GENERATE KG-ENRICHED DEFENDER INPUT ====="

ssh defender '
set -euo pipefail

python3 \
  ~/ecpomdg/kg_defender_integration/app/defender_kg_enriched_observation_client.py
'


# ================================================================
# 12. INDEPENDENT RESULT VALIDATION
# ================================================================

echo
echo "===== INDEPENDENT KG-ENRICHED INPUT VALIDATION ====="

ssh defender python3 - <<'PY'
import json
from pathlib import Path


ROOT = (
    Path.home()
    / "ecpomdg"
    / "kg_defender_integration"
    / "results"
)

snapshot = json.loads(
    (
        ROOT
        / "defender_kg_enriched_observations_snapshot.json"
    ).read_text(
        encoding="ascii"
    )
)


rows = snapshot[
    "observations"
]

schema = snapshot[
    "vector_schema"
]


assert len(schema) == 15
assert len(rows) >= 10


real = [
    row
    for row in rows
    if row[
        "asset_role"
    ] == "real"
]

decoy = [
    row
    for row in rows
    if row[
        "asset_role"
    ] == "decoy"
]


assert real
assert decoy


for row in real:

    if row[
        "kg_context"
    ][
        "control_point"
    ]:

        assert row[
            "physical_grid_connected"
        ] is True

        assert row[
            "kg_context"
        ][
            "physical_control_context"
        ]


for row in decoy:

    if row[
        "kg_context"
    ][
        "control_point"
    ]:

        assert row[
            "physical_grid_connected"
        ] is False

        assert row[
            "kg_context"
        ][
            "represented_component_context"
        ]

        assert not row[
            "kg_context"
        ][
            "physical_control_context"
        ]


latest = rows[-1]

print(
    "observation count:",
    len(rows)
)

print(
    "vector dimension:",
    len(schema)
)

print(
    "latest asset:",
    latest[
        "asset_id"
    ]
)

print(
    "latest role:",
    latest[
        "asset_role"
    ]
)

print(
    "latest IOA:",
    latest[
        "ioa"
    ]
)

print(
    "latest KG rules:",
    latest[
        "kg_context"
    ][
        "matched_rule_ids"
    ]
)

print(
    "latest ATT&CK context:",
    [
        row[
            "technique_id"
        ]
        for row in latest[
            "kg_context"
        ][
            "attack_context"
        ]
    ]
)


print(
    "REAL_ASSET_PHYSICAL_CONTEXT: PASS"
)

print(
    "DECOY_ASSET_DECEPTION_CONTEXT: PASS"
)

print(
    "KG_ENRICHED_DEFENDER_INPUT_VALIDATION: PASS"
)
PY


# ================================================================
# 13. COPY FINAL ARTIFACTS
# ================================================================

echo
echo "===== COPY FINAL KG-INTEGRATION ARTIFACTS ====="

scp \
  defender:~/ecpomdg/kg_defender_integration/results/defender_kg_enriched_observations_snapshot.json \
  "$AUDIT/"

scp \
  defender:~/ecpomdg/kg_defender_integration/results/defender_kg_enriched_observation_vectors.jsonl \
  "$AUDIT/"

scp \
  kg:~/ecpomdg/kg_defender_integration/results/defender_knowledge_context_service.log \
  "$AUDIT/"


# ================================================================
# 14. FREEZE
# ================================================================

echo
echo "===== FREEZE LIVE KG INTEGRATION ====="

sha256sum \
  "$SETUP/defender_knowledge_context_service.py" \
  "$SETUP/defender_kg_enriched_observation_client.py" \
  "$AUDIT/defender_kg_enriched_observations_snapshot.json" \
  "$AUDIT/defender_kg_enriched_observation_vectors.jsonl" \
  "$AUDIT/defender_knowledge_context_service.log" \
  "$AUDIT/kg_integration_real_live_probe.log" \
  "$AUDIT/kg_integration_decoy_live_probe.log" \
  > \
  "$AUDIT/live_kg_enriched_defender_observation_sha256.txt"


cat \
  "$AUDIT/live_kg_enriched_defender_observation_sha256.txt"


echo
echo "================================================================"
echo "LIVE_KG_ENRICHED_DEFENDER_OBSERVATION_INTEGRATION: PASS"
echo "================================================================"

