#!/usr/bin/env bash
# Poke the gated MCP endpoint by hand, without an agent.
#
#   ./try.sh tools investigator
#   ./try.sh tools operator
#   ./try.sh call investigator get-service-health '{"path_service":"checkout"}'
#   ./try.sh call investigator rollback-deployment '{"path_deployment_id":"dep-482"}'
#   ./try.sh call operator     rollback-deployment '{"path_deployment_id":"dep-482"}'
#   ./try.sh tools anonymous
#
# Does the full MCP streamable-HTTP handshake for you:
#   initialize -> capture Mcp-Session-Id -> notifications/initialized -> your call
set -uo pipefail
cd "$(dirname "$0")"
set -a; source .env; set +a

ACTION="${1:-}"; WHO="${2:-investigator}"
case "$WHO" in
  investigator) KEY="$INVESTIGATOR_KEY" ;;
  operator)     KEY="$OPERATOR_KEY" ;;
  anonymous)    KEY="" ;;
  *) echo "identity must be investigator | operator | anonymous"; exit 1 ;;
esac

H=(-H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream')
[ -n "$KEY" ] && H+=(-H "apikey: $KEY")

# 1. initialize, keeping headers so we can read the session id
RESP=$(curl -s -D /tmp/.mcp-h -o /tmp/.mcp-b -w '%{http_code}' "${H[@]}" -X POST "$MCP_URL" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"try.sh","version":"1"}}}')

if [ "$RESP" != "200" ]; then
  echo "identity: $WHO"
  echo "initialize -> HTTP $RESP"
  [ "$RESP" = "401" ] && echo "  Kong rejected the caller before any tool was considered."
  exit 0
fi

SID=$(grep -i '^mcp-session-id:' /tmp/.mcp-h | tr -d '\r' | awk '{print $2}')
H+=(-H "Mcp-Session-Id: $SID")

# 2. complete the handshake
curl -s -o /dev/null "${H[@]}" -X POST "$MCP_URL" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

unwrap() {  # pull JSON out of a plain body or an SSE data: frame
  python3 -c '
import json,sys
raw=sys.stdin.read()
for line in raw.splitlines():
    if line.startswith("data:"): raw=line[5:].strip(); break
try: print(json.dumps(json.loads(raw)))
except Exception: print(json.dumps({"_raw": raw[:300]}))
'
}

case "$ACTION" in
  tools)
    echo "identity: $WHO"
    curl -s "${H[@]}" -X POST "$MCP_URL" \
      -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | unwrap | python3 -c '
import json,sys
d=json.load(sys.stdin)
t=(d.get("result") or {}).get("tools") or []
print("  %d tools visible:" % len(t))
for x in sorted(t, key=lambda i: i["name"]):
    ann = x.get("annotations") or {}
    destr = ann.get("destructiveHint") or ann.get("destructive_hint")
    print("    %-22s%s" % (x["name"], "  [destructive]" if destr else ""))
'
    ;;
  call)
    TOOL="${3:?tool name required}"; ARGS="${4:-{\}}"
    CODE=$(curl -s -o /tmp/.mcp-c -w '%{http_code}' "${H[@]}" -X POST "$MCP_URL" \
      -d "{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/call\",\"params\":{\"name\":\"$TOOL\",\"arguments\":$ARGS}}")
    echo "identity: $WHO   tool: $TOOL   ->   HTTP $CODE"
    if [ "$CODE" = "403" ]; then
      echo "  Kong refused it. The ops API was never contacted."
    else
      unwrap < /tmp/.mcp-c | python3 -c '
import json,sys
d=json.load(sys.stdin)
c=(d.get("result") or {}).get("content") or []
for i in c:
    if i.get("type")=="text":
        t=i["text"]
        try: print("  "+json.dumps(json.loads(t),indent=2).replace("\n","\n  ")[:1200])
        except Exception: print("  "+t[:800])
'
    fi
    ;;
  *)
    sed -n '3,12p' "$0" | sed 's/^# \{0,1\}//'
    ;;
esac
