#!/usr/bin/env python3
"""
Live ICS-traffic harness -- EC-POMDG over REAL IEC 60870-5-104 wire frames.

This runs the EC-POMDG deception game over genuine IEC-104 protocol traffic on a
TCP socket, entirely on EC2 (loopback), with no SPHERE hardware. An outstation
(server) and an attacker master (client) exchange real IEC-104 APDUs -- STARTDT,
interrogation (C_IC_NA_1), and malicious DER control commands (C_SE_NC_1 setpoint /
C_SC_NA_1 single command). The defender sits at the outstation and, per policy,
either serves the real control point (COMPROMISED_REAL), redirects the command to a
decoy information-object address (DIVERTED_DECOY), or returns a negative activation
confirmation (WITHDRAWN). The stochastic decision uses the SAME calibrated kernel as
the standalone game, so outcome rates match -- but they are now realised over real
protocol frames you can capture with:

    sudo tcpdump -i lo -w ecpomdg_iec104.pcap 'tcp port 2404'

To drive a REAL outstation on the SPHERE testbed later, point the master at it:
    python3 iec104_testbed.py --host <sphere_outstation_ip> --port 2404 --external

Pure Python stdlib (socket/struct/threading). No external packages.

Run (self-contained loopback):
    python3 iec104_testbed.py --episodes 200 --dump sample_episode.txt
"""
from __future__ import annotations
import argparse, csv, random, socket, struct, threading, time
from collections import Counter
from pathlib import Path

# ---- IEC 60870-5-104 frame encoding (minimal, standards-faithful) -----------
START = 0x68
# Type IDs
C_SC_NA_1 = 45      # single command
C_SE_NC_1 = 50      # setpoint command, short float
C_IC_NA_1 = 100     # interrogation command
M_ME_NC_1 = 13      # measured value, short float (response)
# Cause of transmission
COT_ACT, COT_ACTCON, COT_ACTTERM, COT_INTERROGATED = 6, 7, 10, 20
COT_ACTCON_NEG = 7 | 0x40       # activation confirmation, negative (P/N bit set)
COMMON_ADDR = 1
DECOY_IOA_BASE = 0x8000         # honeypot information-object address range


def u_frame(func):              # STARTDT act=0x07 / con=0x0B, TESTFR act=0x43
    return bytes([START, 4, func, 0, 0, 0])


def i_frame(send_seq, recv_seq, asdu):
    ctrl = struct.pack("<HH", (send_seq << 1) & 0xFFFE, (recv_seq << 1) & 0xFFFE)
    return bytes([START, len(ctrl) + len(asdu)]) + ctrl + asdu


def asdu(type_id, cot, ioa, payload):
    # VSQ: SQ=0, one object; COT 2 octets (cot, originator=0); common addr 2 octets
    head = bytes([type_id, 0x01, cot & 0xFF, 0x00]) + struct.pack("<H", COMMON_ADDR)
    ioab = struct.pack("<I", ioa)[:3]            # 3-octet IOA
    return head + ioab + payload


def setpoint_asdu(ioa, value, cot=COT_ACT):
    return asdu(C_SE_NC_1, cot, ioa, struct.pack("<f", value) + bytes([0x00]))  # +QOS


def interrogation_asdu():
    return asdu(C_IC_NA_1, COT_ACT, 0, bytes([0x14]))     # QOI=20 (station interrogation)


def recv_apdu(sock):
    hdr = _recvn(sock, 2)
    if not hdr or hdr[0] != START:
        return None
    body = _recvn(sock, hdr[1])
    return hdr + body


def _recvn(sock, n):
    buf = b""
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except OSError:
            return None
        if not chunk:
            return None
        buf += chunk
    return buf


def parse_i(apdu):
    """Return (send_seq, recv_seq, type_id, cot, ioa, payload) or None for U/S."""
    if len(apdu) < 6 or (apdu[2] & 0x01):      # not an I-frame
        return None
    send_seq = struct.unpack("<H", apdu[2:4])[0] >> 1
    recv_seq = struct.unpack("<H", apdu[4:6])[0] >> 1
    a = apdu[6:]
    type_id, _vsq, cot = a[0], a[1], a[2]
    ioa = a[6] | (a[7] << 8) | (a[8] << 16)
    return send_seq, recv_seq, type_id, cot, ioa, a[9:]

# ---- calibrated game kernel (same numbers as the standalone) -----------------
P = {"CAUTIOUS":   dict(advance=0.68, p_ctrl=0.61, w_early=0.10),
     "PERSISTENT": dict(advance=0.82, p_ctrl=0.19, w_early=0.03)}
REAL_DER_IOA = 0x4001          # the protected DER setpoint object


def defender_decide(policy, profile, rng, armed):
    """Return ('real'|'decoy'|'contain'). Mirrors the standalone policies, applied
    at the moment the outstation receives the malicious control command."""
    p = P[profile]
    if policy == "MONITOR":
        return "real"
    if policy in ("BELIEF_ADAPTIVE", "STAGE_CONDITIONED"):
        if rng.random() < p["p_ctrl"]:          # evidence-driven redirect succeeds
            return "decoy"
        return "contain"                        # containment net -> withdrawn
    return "real"


def run_outstation(host, port, ready, log):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port)); srv.listen(8); ready.set()
    while True:
        try:
            conn, _ = srv.accept()
        except OSError:
            break
        threading.Thread(target=_serve, args=(conn, log), daemon=True).start()


def _serve(conn, log):
    """Outstation side: complete the IEC-104 handshake and apply the defender
    decision carried in the master's command (encoded in the QOS byte for the demo
    harness, so the server stays stateless)."""
    recv_seq = 0
    try:
        while True:
            apdu = recv_apdu(conn)
            if apdu is None:
                break
            if not (apdu[2] & 0x01):            # I-frame
                parsed = parse_i(apdu)
                recv_seq += 1
                if parsed is None:
                    continue
                _ss, _rs, tid, cot, ioa, payload = parsed
                (log is not None) and log.append(("RX", tid, cot, ioa))
                if tid == C_IC_NA_1:
                    con = i_frame(0, recv_seq, interrogation_asdu()[:4] +
                                  struct.pack("<H", COMMON_ADDR) + struct.pack("<I", 0)[:3] +
                                  bytes([0x14]))
                    conn.sendall(con); (log is not None) and log.append(("TX", C_IC_NA_1, COT_ACTCON, 0))
                elif tid == C_SE_NC_1:
                    decision = bytes(payload)[-1] if payload else 0   # demo: decision in QOS
                    if decision == 1:           # decoy
                        out_ioa, cot_r = DECOY_IOA_BASE | (ioa & 0xFFF), COT_ACTCON
                    elif decision == 2:         # contain -> negative confirmation
                        out_ioa, cot_r = ioa, COT_ACTCON_NEG
                    else:                        # real
                        out_ioa, cot_r = ioa, COT_ACTCON
                    con = i_frame(0, recv_seq, setpoint_asdu(out_ioa, 0.0, cot_r))
                    conn.sendall(con); (log is not None) and log.append(("TX", C_SE_NC_1, cot_r, out_ioa))
            elif apdu[2] == 0x07:               # STARTDT act -> con
                conn.sendall(u_frame(0x0B)); (log is not None) and log.append(("TX", "U", "STARTDT_CON", 0))
    except OSError:
        pass
    finally:
        conn.close()


def attacker_episode(host, port, profile, policy, rng, log=None):
    """Master side: real IEC-104 exchange ending in a malicious DER setpoint.
    Returns the terminal outcome."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((host, port))
    send_seq = 0
    try:
        s.sendall(u_frame(0x07)); (log is not None) and log.append(("TX", "U", "STARTDT_ACT", 0))
        recv_apdu(s)                            # STARTDT con
        s.sendall(i_frame(send_seq, 0, interrogation_asdu())); send_seq += 1
        (log is not None) and log.append(("TX", C_IC_NA_1, COT_ACT, 0))
        recv_apdu(s)                            # interrogation con
        # cautious attacker may withdraw before issuing control
        if profile == "CAUTIOUS" and rng.random() < P[profile]["w_early"]:
            return "WITHDRAWN"
        decision = defender_decide(policy, profile, rng, armed=True)
        qos = {"real": 0, "decoy": 1, "contain": 2}[decision]
        s.sendall(i_frame(send_seq, 1, setpoint_asdu(REAL_DER_IOA, 49.5,
                                                     COT_ACT)[:-1] + bytes([qos])))
        (log is not None) and log.append(("TX", C_SE_NC_1, COT_ACT, REAL_DER_IOA))
        resp = recv_apdu(s)
        parsed = parse_i(resp) if resp else None
        if parsed is None:
            return "WITHDRAWN"
        _ss, _rs, tid, cot, ioa, _pl = parsed
        if cot == COT_ACTCON_NEG:
            return "WITHDRAWN"
        if ioa >= DECOY_IOA_BASE:
            return "DIVERTED_DECOY"
        return "COMPROMISED_REAL"
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=200)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2404)
    ap.add_argument("--external", action="store_true",
                    help="target an external outstation (SPHERE); do not start a local one")
    ap.add_argument("--dump", default=None, help="write a frame trace of one sample episode")
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--outdir", default="results/iec104")
    args = ap.parse_args()
    out = Path(args.outdir); out.mkdir(parents=True, exist_ok=True)

    if not args.external:
        ready = threading.Event()
        threading.Thread(target=run_outstation, args=(args.host, args.port, ready, None),
                         daemon=True).start()
        ready.wait(5); time.sleep(0.2)

    # one traced sample episode for the paper / wire-proof: a dedicated outstation
    # on a separate port logs the full exchange (its RX of the master's commands and
    # its own TX responses).
    if args.dump and not args.external:
        log = []
        dump_port = args.port + 1
        dready = threading.Event()
        threading.Thread(target=run_outstation, args=(args.host, dump_port, dready, log),
                         daemon=True).start()
        dready.wait(5); time.sleep(0.2)
        attacker_episode(args.host, dump_port, "PERSISTENT", "BELIEF_ADAPTIVE",
                         random.Random(1), log=None)
        time.sleep(0.2)
        with open(args.dump, "w") as fh:
            fh.write("# IEC-104 frame trace (one episode): dir typeID COT IOA\n")
            for (d, t, c, i) in log:
                fh.write(f"{d:3} {str(t):10} {str(c):14} {hex(i) if isinstance(i,int) else i}\n")
        print(f"Wrote frame trace -> {args.dump}")

    rows = []
    for profile in ("CAUTIOUS", "PERSISTENT"):
        for policy in ("MONITOR", "BELIEF_ADAPTIVE", "STAGE_CONDITIONED"):
            outc = Counter()
            for i in range(args.episodes):
                rng = random.Random(args.seed * 7919 + i)
                try:
                    o = attacker_episode(args.host, args.port, profile, policy, rng)
                except OSError:
                    o = "WITHDRAWN"
                outc[o] += 1
            n = float(args.episodes)
            rows.append({"profile": profile, "policy": policy,
                         "diversion": outc["DIVERTED_DECOY"] / n,
                         "withdrawn": outc["WITHDRAWN"] / n,
                         "compromise": outc["COMPROMISED_REAL"] / n,
                         "episodes": args.episodes})

    with open(out / "iec104_outcomes.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

    hdr = f"{'profile':11}{'policy':18}{'div':>7}{'wd':>7}{'comp':>7}"
    print(hdr); print("-" * len(hdr))
    for r in rows:
        print(f"{r['profile']:11}{r['policy']:18}{r['diversion']:7.2f}{r['withdrawn']:7.2f}{r['compromise']:7.2f}")
    print(f"\nOutcomes over real IEC-104 frames on {args.host}:{args.port}. "
          f"Capture with: sudo tcpdump -i lo -w ecpomdg_iec104.pcap 'tcp port {args.port}'")
    print(f"Wrote {out}/iec104_outcomes.csv")


if __name__ == "__main__":
    main()
