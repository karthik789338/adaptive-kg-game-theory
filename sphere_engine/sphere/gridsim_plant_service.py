#!/usr/bin/env python3
"""Reconstructed gridsim plant service (10.40.0.20:8765).

The original OpenDSS IEEE-13 plant service was not captured in the backup, so
this rebuilds the SAME HTTP API your controller expects, using the exact linear
voltage model your controller already carries for the decoy
(iec104_controller_decoy_service.py). Endpoints:

    GET  /state            -> {"ok":true,"state":{...}}
    POST /command {p_kw,q_kvar} -> applies a setpoint, returns new state
    POST /reset   {}        -> resets to nominal, returns state

State fields: command_p_kw, command_q_kvar, p_injection_kw, q_injection_kvar,
bus675_mean_voltage_pu.

FIDELITY NOTE: this is a transparent linear surrogate of the IEEE-13 feeder's
bus-675 voltage response (identical to the controller's own model), NOT the
original OpenDSS solver. For H1 it is behaviorally exact because the REAL
controller never executes (the plant stays at nominal); a setpoint only ever
reaches the decoy. If you later run experiments that command the REAL plant,
swap this for your OpenDSS service.

Run on gridsim:  python3 gridsim_plant_service.py --bind 0.0.0.0 --port 8765
"""
from __future__ import annotations
import argparse
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

P_MAX_KW = 400.0
Q_MAX_KVAR = 300.0

# Exact model lifted from iec104_controller_decoy_service.py
BASE_VOLTAGE = 0.9939529864481482
P_VOLTAGE_GAIN = (0.9992831675254893 - BASE_VOLTAGE) / 400.0
Q_VOLTAGE_GAIN = (1.0081993790101325 - 0.9923966962484867) / 600.0

NOMINAL_STATE = {
    "command_p_kw": 400.0,
    "command_q_kvar": 0.0,
    "p_injection_kw": 400.00338507478705,
    "q_injection_kvar": 0.002546371300089959,
    "bus675_mean_voltage_pu": 0.9992831675254893,
}

LOG = Path.home() / "ecpomdg" / "t2_gridsim" / "logs" / "plant_service_events.jsonl"
STATE_LOCK = threading.RLock()
STATE = dict(NOMINAL_STATE)


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _log(event, **fields):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts_utc": _utc(), "event": event, **fields}
    with LOG.open("a") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")


def _apply(p_kw, q_kvar):
    p_kw = float(p_kw)
    q_kvar = float(q_kvar)
    if not (0.0 <= p_kw <= P_MAX_KW):
        raise ValueError("P outside allowed range")
    if not (-Q_MAX_KVAR <= q_kvar <= Q_MAX_KVAR):
        raise ValueError("Q outside allowed range")
    voltage = BASE_VOLTAGE + P_VOLTAGE_GAIN * p_kw + Q_VOLTAGE_GAIN * q_kvar
    return {"command_p_kw": p_kw, "command_q_kvar": q_kvar,
            "p_injection_kw": p_kw, "q_injection_kvar": q_kvar,
            "bus675_mean_voltage_pu": voltage}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # silence default stderr logging
        return

    def do_GET(self):
        if self.path.rstrip("/") == "/state":
            with STATE_LOCK:
                self._send(200, {"ok": True, "state": dict(STATE)})
        else:
            self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        global STATE
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except Exception:
            payload = {}
        path = self.path.rstrip("/")
        if path == "/reset":
            with STATE_LOCK:
                STATE = dict(NOMINAL_STATE)
                _log("reset", state=STATE)
                self._send(200, {"ok": True, "state": dict(STATE)})
        elif path == "/command":
            try:
                new = _apply(payload.get("p_kw"), payload.get("q_kvar"))
            except Exception as exc:
                self._send(400, {"ok": False, "error": str(exc)})
                return
            with STATE_LOCK:
                STATE = dict(new)
                _log("command", request=payload, state=STATE)
                self._send(200, {"ok": True, "state": dict(STATE)})
        else:
            self._send(404, {"ok": False, "error": "not found"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    _log("startup", bind=args.bind, port=args.port, model="linear_surrogate")
    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    print(f"PLANT_SERVICE_LISTENING: {args.bind}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
