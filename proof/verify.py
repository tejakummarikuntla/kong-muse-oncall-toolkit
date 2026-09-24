#!/usr/bin/env python3
"""
Proves the on-call toolkit's access model without spending a Muse prompt.

Speaks the MCP streamable-HTTP handshake directly against Kong, once per
identity, and asserts what each identity can see and do:

  anonymous     -> 401, no tool list at all
  investigator  -> 7 tools, rollback-deployment absent from tools/list,
                   403 if it calls rollback-deployment anyway,
                   create-incident succeeds
  operator      -> 8 tools, rollback-deployment present and it works

Usage:
  export MCP_URL=http://localhost:8000/ops-mcp
  export INVESTIGATOR_KEY=... OPERATOR_KEY=...
  python3 verify.py
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

MCP_URL = os.environ.get("MCP_URL", "http://localhost:8000/ops-mcp")
INVESTIGATOR_KEY = os.environ.get("INVESTIGATOR_KEY", "")
OPERATOR_KEY = os.environ.get("OPERATOR_KEY", "")

PROTOCOL = "2025-06-18"

results: list[tuple[bool, str, str]] = []


def check(ok: bool, label: str, detail: str = "") -> bool:
    results.append((ok, label, detail))
    mark = "PASS" if ok else "FAIL"
    line = f"  {mark}  {label}"
    if detail:
        line += f"   | {detail}"
    print(line)
    return ok


# ------------------------------------------------------------------ transport

def post(payload: dict, key: str | None, session: str | None):
    """POST one JSON-RPC message. Returns (status, headers, parsed_or_None)."""
    body = json.dumps(payload).encode()
    req = urllib.request.Request(MCP_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    # Streamable HTTP: the server may answer as JSON or as an SSE stream.
    req.add_header("Accept", "application/json, text/event-stream")
    req.add_header("MCP-Protocol-Version", PROTOCOL)
    if key:
        req.add_header("apikey", key)
    if session:
        req.add_header("Mcp-Session-Id", session)

    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, dict(r.headers), decode(r.read(), r.headers)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), decode(e.read(), e.headers)
    except urllib.error.URLError as e:
        print(f"\n  transport error talking to {MCP_URL}: {e.reason}")
        sys.exit(2)


def decode(raw: bytes, headers) -> dict | None:
    """Parse a JSON body, or pull the first data: frame out of an SSE stream."""
    if not raw:
        return None
    ctype = (headers.get("Content-Type") or "").lower()
    text = raw.decode("utf-8", "replace")
    if "text/event-stream" in ctype:
        for line in text.splitlines():
            if line.startswith("data:"):
                try:
                    return json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    return None
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Kong denies with an nginx HTML body rather than JSON-RPC.
        return {"_raw": text[:200]}


def handshake(key: str | None):
    """initialize -> notifications/initialized. Returns (status, session_id)."""
    status, headers, _ = post(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "oncall-verify", "version": "1.0"},
            },
        },
        key,
        None,
    )
    if status != 200:
        return status, None
    session = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
    post({"jsonrpc": "2.0", "method": "notifications/initialized"}, key, session)
    return status, session


def tools_list(key: str, session: str | None) -> list[str]:
    _, _, data = post(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, key, session
    )
    tools = ((data or {}).get("result") or {}).get("tools") or []
    return sorted(t["name"] for t in tools)


def tools_call(key: str, session: str | None, name: str, args: dict):
    return post(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        },
        key,
        session,
    )


def payload_text(data: dict | None) -> str:
    """Unwrap the text content of a successful tools/call result."""
    content = ((data or {}).get("result") or {}).get("content") or []
    for item in content:
        if item.get("type") == "text":
            return item.get("text", "")
    return ""


# ------------------------------------------------------------------ the runs

READ_TOOLS = {
    "get-service-health",
    "list-deployments",
    "get-error-summary",
    "get-error-samples",
    "search-runbooks",
    "get-runbook",
}
INVESTIGATOR_EXPECTED = sorted(READ_TOOLS | {"create-incident"})
OPERATOR_EXPECTED = sorted(READ_TOOLS | {"create-incident", "rollback-deployment"})


def run_anonymous():
    print("\n[anonymous] no credential")
    status, _ = handshake(None)
    check(status == 401, "anonymous -> 401", f"status={status}")


def run_investigator() -> str | None:
    print("\n[investigator] key in group incident-response")
    status, session = handshake(INVESTIGATOR_KEY)
    if not check(status == 200, "handshake -> 200", f"status={status}"):
        return None

    names = tools_list(INVESTIGATOR_KEY, session)
    check(
        names == INVESTIGATOR_EXPECTED,
        f"tools/list shows {len(INVESTIGATOR_EXPECTED)} tools",
        f"got {len(names)}: {names}",
    )
    check(
        "rollback-deployment" not in names,
        "rollback-deployment absent from tools/list",
    )

    # Diagnostics work.
    st, _, data = tools_call(
        INVESTIGATOR_KEY, session, "get-service-health", {"path_service": "checkout"}
    )
    body = payload_text(data)
    check(
        st == 200 and "degraded" in body,
        "get-service-health -> degraded",
        f"status={st}",
    )

    st, _, data = tools_call(
        INVESTIGATOR_KEY,
        session,
        "get-error-summary",
        {"query_service": "checkout", "query_minutes": 60},
    )
    check(
        st == 200 and "PaymentProviderTimeout" in payload_text(data),
        "get-error-summary -> PaymentProviderTimeout present",
        f"status={st}",
    )

    # The safe write is allowed.
    st, _, data = tools_call(
        INVESTIGATOR_KEY,
        session,
        "create-incident",
        {
            "body": {
                "title": "checkout: payment provider timeouts after dep-482",
                "service": "checkout",
                "severity": "sev2",
                "summary": "Error onset correlates with dep-482 connection pooling change.",
            }
        },
    )
    inc_body = payload_text(data)
    incident_id = None
    if st == 200:
        try:
            incident_id = json.loads(inc_body).get("id")
        except json.JSONDecodeError:
            pass
    check(
        st == 200 and incident_id is not None,
        "create-incident -> allowed",
        f"status={st} incident={incident_id}",
    )

    # The production change is refused.
    st, _, data = tools_call(
        INVESTIGATOR_KEY,
        session,
        "rollback-deployment",
        {"path_deployment_id": "dep-482", "body": {"reason": "attempted by investigator"}},
    )
    check(st == 403, "rollback-deployment -> 403", f"status={st}")

    return incident_id


def run_operator(incident_id: str | None):
    print("\n[operator] key in group sre-oncall")
    status, session = handshake(OPERATOR_KEY)
    if not check(status == 200, "handshake -> 200", f"status={status}"):
        return

    names = tools_list(OPERATOR_KEY, session)
    check(
        names == OPERATOR_EXPECTED,
        f"tools/list shows {len(OPERATOR_EXPECTED)} tools",
        f"got {len(names)}: {names}",
    )
    check("rollback-deployment" in names, "rollback-deployment visible")

    st, _, data = tools_call(
        OPERATOR_KEY,
        session,
        "rollback-deployment",
        {
            "path_deployment_id": "dep-482",
            "body": {
                "incident_ref": incident_id or "INC-1001",
                "reason": "rb-204: onset correlates with deploy; roll back first",
            },
        },
    )
    body = payload_text(data)
    ok = st == 200 and '"status": "completed"' in body
    restored = ""
    if st == 200:
        try:
            restored = json.loads(body).get("restored", "")
        except json.JSONDecodeError:
            pass
    check(ok, "rollback-deployment -> completed", f"status={st} restored={restored}")


AUDIT_LOG = "/tmp/oncall-audit.jsonl"


def run_audit_checks():
    """Assert against Kong's own log what the gateway recorded and refused."""
    print("\n[audit] Kong's http-log output")

    # http-log flushes asynchronously, so the last entries land after the HTTP
    # responses we already asserted on. Poll until both decisions show up.
    denies: list[tuple[dict, dict]] = []
    allows: list[tuple[dict, dict]] = []
    for attempt in range(20):
        try:
            rows = [json.loads(l) for l in open(AUDIT_LOG)]
        except FileNotFoundError:
            check(False, "audit log present",
                  f"{AUDIT_LOG} not found (is auditsink.py running?)")
            return
        denies, allows = [], []
        for r in rows:
            for a in ((r.get("ai") or {}).get("mcp") or {}).get("audit") or []:
                (denies if a.get("action") == "deny" else allows).append((a, r))
        have_deny = any(a.get("primitive_name") == "rollback-deployment" for a, _ in denies)
        have_allow = any(
            a.get("primitive_name") == "rollback-deployment"
            and (a.get("consumer") or {}).get("name") == "sre-oncall"
            for a, _ in allows
        )
        if have_deny and have_allow:
            break
        time.sleep(0.5)

    match = [
        (a, r) for a, r in denies if a.get("primitive_name") == "rollback-deployment"
    ]
    if not check(len(match) == 1, "exactly one deny recorded", f"got {len(denies)}"):
        return
    a, r = match[0]

    check(
        (a.get("consumer") or {}).get("name") == "oncall-investigator",
        "deny names the caller",
        f"{(a.get('consumer') or {}).get('name')} "
        f"(identifier={(a.get('consumer') or {}).get('identifier')})",
    )
    # The load-bearing claim: Kong refused before opening any upstream socket.
    check(
        r.get("upstream_status") in ("", None),
        "denied call never reached the ops API",
        f"upstream_status={r.get('upstream_status')!r} "
        f"proxy_latency={(r.get('latencies') or {}).get('proxy')}",
    )
    check(
        any(
            x.get("primitive_name") == "rollback-deployment"
            and (x.get("consumer") or {}).get("name") == "sre-oncall"
            for x, _ in allows
        ),
        "same tool allowed for sre-oncall",
    )


if __name__ == "__main__":
    if not INVESTIGATOR_KEY or not OPERATOR_KEY:
        sys.exit("set INVESTIGATOR_KEY and OPERATOR_KEY first")

    print(f"MCP endpoint: {MCP_URL}")
    run_anonymous()
    incident = run_investigator()
    run_operator(incident)
    run_audit_checks()

    passed = sum(1 for ok, _, _ in results if ok)
    total = len(results)
    print(f"\n{passed}/{total} passed")
    sys.exit(0 if passed == total else 1)
