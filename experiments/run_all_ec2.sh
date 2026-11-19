#!/usr/bin/env bash
# ============================================================================
# EC-POMDG novelty experiments N1/N2/N3 -- one-shot runner for the g6.4xlarge EC2
# (or the SPHERE node). Pure Python stdlib; no ec_pomdg dependency, no GPU needed.
#
#   bash run_all_ec2.sh
#
# Writes CSVs under results/.  Camera-ready seed counts; drop --seeds/--episodes/
# --attacks if you want a quicker smoke test.
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p results

echo "=============================================================="
echo " N1  deception-aware attacker + stage-conditioned defense"
echo "=============================================================="
python3 ecpomdg_standalone.py --seeds 20000 --budgets 3 4 5 6 7 8 \
    --attacker both --outdir results/stage_conditioned

echo
echo "=============================================================="
echo " N2  online-KG Bayesian likelihood (vs static / oracle)"
echo "=============================================================="
python3 n2_online_kg.py --episodes 20000 --seed 7 --outdir results/n2

echo
echo "=============================================================="
echo " N3  cyber-physical coupling (linear feeder sensitivity)"
echo "=============================================================="
python3 n3_cyber_physical.py --attacks 50000 --budgets 1 2 3 4 --seed 11 \
    --outdir results/n3

echo
echo "=============================================================="
echo " N3-OpenDSS  cyber-physical coupling (REAL non-linear power flow)"
echo "=============================================================="
if python3 -c "import opendssdirect" 2>/dev/null; then
    python3 n3_opendss.py --attacks 50000 --budgets 1 2 3 4 --seed 11 \
        --outdir results/n3_opendss
else
    echo "  opendssdirect not installed -- skipping. To enable:"
    echo "    pip install --break-system-packages opendssdirect.py"
    echo "    python3 n3_opendss.py --attacks 50000 --budgets 1 2 3 4 --seed 11"
fi

echo
echo "=============================================================="
echo " LIVE ICS TRAFFIC  EC-POMDG over real IEC-104 frames (loopback)"
echo "=============================================================="
python3 iec104_testbed.py --episodes 500 --dump results/iec104/sample_episode.txt \
    --outdir results/iec104

echo
echo "All done. CSVs:"
echo "  results/stage_conditioned/h1_stage_conditioned.csv   (N1)"
echo "  results/n2/n2_online_kg.csv                           (N2)"
echo "  results/n3/n3_cyber_physical.csv                      (N3 linear)"
echo "  results/n3_opendss/n3_opendss.csv                     (N3 OpenDSS, if installed)"
echo "  results/iec104/iec104_outcomes.csv                    (live IEC-104 traffic)"
echo
echo "Capture the live IEC-104 frames as a pcap (optional):"
echo "  sudo tcpdump -i lo -w ecpomdg_iec104.pcap 'tcp port 2404' &"
echo "  python3 iec104_testbed.py --episodes 500"
echo "To drive a real SPHERE outstation later:"
echo "  python3 iec104_testbed.py --host <sphere_ip> --port 2404 --external"
