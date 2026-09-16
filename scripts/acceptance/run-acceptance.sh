#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
exec bash scripts/team-acceptance.sh "${BANKPULSE_URL:-http://localhost:8080}"
