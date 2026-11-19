#!/usr/bin/env bash
# Fetch the official IEEE 123-bus test feeder (dss-extensions mirror) into ./ieee123/
# for n3_ieee123.py. The IEEE test feeders are a standard public benchmark.
set -e
mkdir -p ieee123
B=https://raw.githubusercontent.com/dss-extensions/electricdss-tst/master/Version8/Distrib/IEEETestCases
for f in IEEE123Master.dss IEEE123Regulators.DSS IEEE123Loads.DSS; do
  curl -sSL -o "ieee123/$f" "$B/123Bus/$f"
done
# shared line-codes referenced by the master as ../IEEELineCodes.DSS
curl -sSL -o "IEEELineCodes.DSS" "$B/IEEELineCodes.DSS"
echo "IEEE-123 feeder fetched into ./ieee123/ (+ IEEELineCodes.DSS alongside)."
echo "Verify:  python3 -c \"import opendssdirect as d; d.Text.Command('Compile (ieee123/IEEE123Master.dss)'); d.Text.Command('Solve'); print('buses', d.Circuit.NumBuses())\""
