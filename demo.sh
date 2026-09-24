#!/usr/bin/env bash
# On-call toolkit demo driver.
#
#   ./demo.sh up      start the ops API and apply the gateway config
#   ./demo.sh verify  prove the access model with no model in the loop
#   ./demo.sh muse-config  build per-identity Muse configs and print run commands
#   ./demo.sh reset   restart the ops API (re-seeds the incident)
#   ./demo.sh down    stop the ops API
set -euo pipefail
cd "$(dirname "$0")"

[[ -f .env ]] || { echo "missing .env"; exit 1; }
set -a; source .env; set +a

api_up() {
  if lsof -ti:9110 >/dev/null 2>&1; then
    echo "ops-api already on :9110"
  else
    (python3 ops-api/opsapi.py > /tmp/opsapi.log 2>&1 &)
    for _ in $(seq 1 10); do
      sleep 0.3
      curl -sf --max-time 2 http://localhost:9110/v1/incidents >/dev/null 2>&1 && break
    done
    echo "ops-api up on :9110"
  fi
  curl -s "http://localhost:9110/v1/deployments?service=checkout&limit=1" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin)["deployments"][0]; print(f"  seeded: {d[\"id\"]} deployed {d[\"deployed_at\"]}")'
}

case "${1:-}" in
  up)
    api_up
    : "${AI_GATEWAY_ID:?set AI_GATEWAY_ID in .env}"
    echo "applying gateway config..."
    kongctl apply -f oncall-gateway.yaml
    ;;
  verify)
    api_up
    python3 proof/verify.py
    ;;
  muse-config)
    # Muse has no --settings flag; it reads $XDG_CONFIG_HOME/muse/settings.json.
    # Build one config dir per identity so the user's real ~/.config/muse is
    # never touched. The key is written literally because ${VAR} interpolation
    # in mcp_servers.headers does not work in Muse Code 1.3.0.
    for role in investigator operator; do
      d=/tmp/muse-$role/muse; mkdir -p "$d"
      cp ~/.config/muse/auth.json ~/.config/muse/trust.json "$d/" 2>/dev/null
      KEY_VAR=$([ "$role" = investigator ] && echo INVESTIGATOR_KEY || echo OPERATOR_KEY)
      python3 - "$role" "${!KEY_VAR}" <<'PY'
import json, sys
role, key = sys.argv[1], sys.argv[2]
src = f"muse/settings.{role}.json"
dst = f"/tmp/muse-{role}/muse/settings.json"
d = json.load(open(src))
d["mcp_servers"]["oncall"]["headers"]["apikey"] = key
json.dump(d, open(dst, "w"), indent=2)
print(f"  {role:13} -> {dst}")
PY
    done
    cat <<'EOF'

Run the investigation (7 tools, no rollback):
  XDG_CONFIG_HOME=/tmp/muse-investigator muse exec --trust-workspace \
    "Checkout errors increased after the last deployment. Investigate why, using
     the on-call tools available to you. Show the evidence for your conclusion,
     then tell me what should be done about it."

Run the remediation (8 tools):
  XDG_CONFIG_HOME=/tmp/muse-operator muse exec --trust-workspace \
    "Incident INC-1001 is open for the checkout service. Read the incident and
     runbook rb-204, confirm from the evidence whether a rollback is justified,
     and if it is, perform the rollback and report the result."

Free wiring test (connects MCP, never calls the model):
  XDG_CONFIG_HOME=/tmp/muse-investigator muse exec --provider echo "ping"
EOF
    ;;
  reset)
    lsof -ti:9110 2>/dev/null | xargs -r kill -9 || true
    sleep 1
    api_up
    ;;
  down)
    lsof -ti:9110 2>/dev/null | xargs -r kill -9 || true
    echo "ops-api stopped"
    ;;
  *)
    sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
