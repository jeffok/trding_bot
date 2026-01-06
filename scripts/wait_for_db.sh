#!/usr/bin/env bash
set -euo pipefail

echo "[wait_for_db] waiting for ${DB_HOST}:${DB_PORT} ..."

python - <<'PY'
import os, socket, time, sys
host=os.getenv("DB_HOST","")
port=int(os.getenv("DB_PORT","3306"))
deadline=time.time()+60
while time.time()<deadline:
    try:
        s=socket.create_connection((host,port),timeout=3)
        s.close()
        print("[wait_for_db] DB port is open.")
        sys.exit(0)
    except Exception:
        time.sleep(1)
print("[wait_for_db] DB still not reachable after 60s.")
sys.exit(2)
PY

# 可选：等待 Redis（如果配置了 REDIS_URL）
if [ -n "${REDIS_URL:-}" ]; then
  echo "[wait_for_db] checking redis via REDIS_URL ..."
  python - <<'PY'
import os, time, sys
import redis
url=os.getenv("REDIS_URL","").strip()
deadline=time.time()+60
last=None
while time.time()<deadline:
    try:
        r=redis.Redis.from_url(url)
        r.ping()
        print("[wait_for_db] Redis ping ok.")
        sys.exit(0)
    except Exception as e:
        last=e
        time.sleep(1)
print("[wait_for_db] Redis not ready/auth failed:", last)
sys.exit(3)
PY
fi
