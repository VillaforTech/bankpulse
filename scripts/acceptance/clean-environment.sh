#!/usr/bin/env bash
# Run once in a fresh, disposable Codespace/devcontainer. The acceptance suite
# interrupts services and introduces an isolated business mutation.
set -euo pipefail
cd "$(dirname "$0")/../.."
mkdir -p artifacts/runtime
if [[ -f artifacts/runtime/clean-environment-started.txt ]]; then
  echo 'Use a new environment: a previous run may have retained business fixtures.' >&2
  exit 1
fi
date -u +%FT%TZ > artifacts/runtime/clean-environment-started.txt
git rev-parse HEAD > artifacts/runtime/tested-sha.txt
git status --porcelain > artifacts/runtime/worktree-status.txt
capture() {
  result=$?
  trap - EXIT
  printf '%s\n' "$result" > artifacts/runtime/clean-environment-exit.txt
  date -u +%FT%TZ > artifacts/runtime/clean-environment-finished.txt
  docker compose ps --all > artifacts/runtime/containers.txt 2>&1 || true
  docker compose logs --no-color --tail=250 > artifacts/runtime/platform.log 2>&1 || true
  docker compose -f observability/compose.yaml logs --no-color --tail=100 > artifacts/runtime/observability.log 2>&1 || true
  echo "Acceptance exit: $result; evidence: artifacts/"
  exit "$result"
}
trap capture EXIT
{ uname -sm; getconf _NPROCESSORS_ONLN; free -m; df -h /; docker version --format '{{.Server.Version}}'; node --version; python3 --version; } > artifacts/runtime/resources.txt
export ANALYTICS_COVERAGE_FROM="$(date -u +%FT%TZ)"
docker compose up -d --build --wait --wait-timeout 300
docker compose -f compose.yaml -f compose.analytics.yaml up -d --build --wait business-analytics
python3 scripts/analytics-integration.py
bash scripts/smoke-v2.sh
docker compose -f observability/compose.yaml up -d --build prometheus grafana grafana-live-adapter
npm install --prefix /tmp/live-browser playwright@1.51.1
/tmp/live-browser/node_modules/.bin/playwright install --with-deps chromium
export NODE_PATH=/tmp/live-browser/node_modules
node scripts/live-browser-test.cjs
bash scripts/acceptance/run-acceptance.sh
