#!/usr/bin/env bash
set -euo pipefail

echo "[DRILL] Restart data-syncer (sync lag + heartbeat check)"
docker compose restart data-syncer
sleep 5

echo "[DRILL] Query /health"
curl -sS http://localhost:8080/health | python -m json.tool
echo "OK"
