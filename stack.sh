#!/usr/bin/env bash
# Bring the whole demo stack up, whatever state it is currently in.
#
# Docker Desktop on this machine stops its VM fairly often, which takes the
# Kong data plane with it. This waits the daemon out rather than failing.
#
#   ./stack.sh          ensure everything is up
#   ./stack.sh status   report only
set -uo pipefail
cd "$(dirname "$0")"

KONG_CTR=charming_haibt
SUPPORT_CTRS=(blog-redis ai-pii)

say() { printf '  %-28s %s\n' "$1" "$2"; }

ensure_docker() {
  if docker info >/dev/null 2>&1; then say "docker daemon" "up"; return 0; fi
  say "docker daemon" "down, starting Docker Desktop..."
  open -a Docker 2>/dev/null
  for i in $(seq 1 60); do
    sleep 4
    if docker info >/dev/null 2>&1; then say "docker daemon" "up after ~$((i*4))s"; return 0; fi
  done
  say "docker daemon" "FAILED to start after 240s"; return 1
}

ensure_containers() {
  local running
  running=$(docker ps --format '{{.Names}}' 2>/dev/null)
  for c in "$KONG_CTR" "${SUPPORT_CTRS[@]}"; do
    if grep -qx "$c" <<<"$running"; then
      say "$c" "already running"
    else
      docker start "$c" >/dev/null 2>&1 && say "$c" "started" || say "$c" "FAILED to start"
    fi
  done
  for i in $(seq 1 40); do
    sleep 2
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://localhost:8000/ 2>/dev/null)
    [ "$code" != "000" ] && { say "kong :8000" "responding (HTTP $code) after ~$((i*2))s"; return 0; }
  done
  say "kong :8000" "NOT responding"; return 1
}

ensure_python() {
  # Audit sink first, so it captures everything the ops API serves.
  if lsof -ti:9111 >/dev/null 2>&1; then
    say "audit sink :9111" "already running"
  else
    (python3 -u ops-api/auditsink.py > /tmp/auditsink.log 2>&1 &)
    sleep 1; say "audit sink :9111" "started"
  fi
  if lsof -ti:9110 >/dev/null 2>&1; then
    say "ops-api :9110" "already running"
  else
    (python3 ops-api/opsapi.py > /tmp/opsapi.log 2>&1 &)
    for _ in $(seq 1 12); do
      sleep 0.4
      curl -sf --max-time 2 http://localhost:9110/v1/incidents >/dev/null 2>&1 && break
    done
    say "ops-api :9110" "started"
  fi
}

if [ "${1:-}" = "status" ]; then
  docker info >/dev/null 2>&1 && say "docker daemon" "up" || say "docker daemon" "down"
  for p in 8000 9110 9111; do
    lsof -ti:$p >/dev/null 2>&1 && say ":$p" "listening" || say ":$p" "down"
  done
  exit 0
fi

echo "bringing up the on-call demo stack"
ensure_docker   || exit 1
ensure_containers || exit 1
ensure_python
echo "ready"
