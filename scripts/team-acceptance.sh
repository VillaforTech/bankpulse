#!/usr/bin/env bash
# Required acceptance runner once #1/#2/#3/#5 are integrated. Missing/skipped work blocks.
set -euo pipefail
base="${1:-http://localhost:8080}"
mkdir -p artifacts/acceptance
for file in business_test_social_split.py latency_benchmark.py resilience_checks.py; do
  test -f "scripts/acceptance/$file" || { echo "Missing acceptance component: $file" >&2; exit 1; }
done
python3 scripts/acceptance/business_test_social_split.py --base-url "$base" | tee artifacts/acceptance/business.log
python3 scripts/acceptance/latency_benchmark.py --base-url "$base" --out artifacts/acceptance/latency.json | tee artifacts/acceptance/latency.log
python3 scripts/check-panel-evidence.py artifacts/acceptance/latency.json
# Missing, skipped or failed scenarios block the release gate.
python3 scripts/acceptance/resilience_checks.py --base-url "$base" | tee artifacts/acceptance/resilience.log

node scripts/acceptance/deadline-panel.cjs | tee artifacts/acceptance/deadline.log
python3 scripts/acceptance/false_green.py | tee artifacts/acceptance/false-green.log
