#!/usr/bin/env bash
set -euo pipefail

echo "[DRILL] Restart strategy-engine (idempotency/reconcile smoke check)"
docker compose restart strategy-engine
sleep 5

echo "[DRILL] Query /admin/status"
curl -sS http://localhost:8080/admin/status | python -m json.tool | head -n 80
echo "OK"
