#!/usr/bin/env python3
"""
Audit sink for the on-call toolkit demo.

Kong's http-log Policy POSTs one JSON log entry per request here. This renders
the part that matters: who called which tool, and whether Kong allowed it.

Shapes observed from Kong 2.0.3-ai-gateway, which the renderer handles:

  * A denied tool call carries `ai.mcp.audit[]` with `primitive_name`,
    `action: deny`, and the consumer. Its `upstream_status` is empty and
    `latencies.proxy` is -1, because Kong never opened a connection upstream.
  * An allowed tool call carries `ai.mcp.rpc[]` with `tool_name`, and no
    audit array.
  * Each allowed tool call also produces a second entry for the loopback
    request Kong makes to the REST endpoint (uri /ops-mcp/<path>).
  * An unauthenticated request has no `consumer` and no `ai` object at all.

    python3 auditsink.py          # listens on :9111
"""

import json
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 9111
LOGFILE = "/tmp/oncall-audit.jsonl"

# Kong emits a second log entry for the loopback REST call behind each allowed
# tool. It is flushed when that call completes, which is *before* the MCP
# envelope it belongs to, and the two entries share no correlation id -- so
# arrival order cannot be used to pair them. They are hidden by default rather
# than nested misleadingly. Run with --upstream to see them interleaved.
SHOW_UPSTREAM = "--upstream" in sys.argv

_lock = threading.Lock()


def out(*a):
    print(*a, flush=True)


# Kong's `hide_credentials: true` strips the key from the request it sends
# UPSTREAM, but http-log still reports the headers the client sent, so the raw
# API key lands in the log payload. Scrub it before anything touches disk.
SENSITIVE_HEADERS = ("apikey", "authorization", "x-api-key", "cookie")


def redact(entry: dict) -> None:
    for section in ("request", "response"):
        headers = (entry.get(section) or {}).get("headers")
        if isinstance(headers, dict):
            for h in list(headers):
                if h.lower() in SENSITIVE_HEADERS:
                    headers[h] = "<redacted>"


def consumer_of(entry: dict) -> str:
    c = entry.get("consumer") or {}
    return c.get("username") or "anonymous"


def render(entry: dict) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    who = consumer_of(entry)
    resp = entry.get("response") or {}
    status = resp.get("status")
    uri = (entry.get("request") or {}).get("uri", "")
    mcp = ((entry.get("ai") or {}).get("mcp")) or {}

    # The loopback call Kong makes to the REST API once a tool is allowed.
    # Shown indented so allow -> upstream and deny -> silence are both visible.
    if uri.startswith("/ops-mcp/"):
        if SHOW_UPSTREAM:
            up = entry.get("upstream_uri", "?")
            out(f"{ts}  {'  (kong -> ops-api)':21} {up:24} {'':5} HTTP "
                f"{entry.get('upstream_status') or status}")
        return

    audits = mcp.get("audit") or []
    rpcs = mcp.get("rpc") or []

    # ACL decisions. An allow names the consumer_group that granted it; a deny
    # names the caller, because no group matched. A null primitive_name is the
    # tools/list filter rather than a single tool.
    for a in audits:
        action = (a.get("action") or "").upper()
        name = a.get("primitive_name") or "(tool list)"
        c = a.get("consumer") or {}
        ident, rule = c.get("identifier"), c.get("name")
        via = f"group {rule}" if ident == "consumer_group" else "no matching rule"
        out(f"{ts}  {who:21} {name:24} {action:5} HTTP {status}   {via}")

    if audits:
        return

    # Protocol messages (initialize, notifications/initialized) carry no ACL
    # decision of their own.
    for r in rpcs:
        method = r.get("tool_name") or r.get("method") or "?"
        lat = r.get("latency")
        tail = f"   {lat}ms" if lat is not None else ""
        out(f"{ts}  {who:21} {method:24} {'':5} HTTP {status}{tail}")

    # No MCP content at all: rejected before the protocol was parsed.
    if not rpcs:
        out(f"{ts}  {who:21} {'-':24} {'':5} HTTP {status}   no credential")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()
        if not raw:
            return
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        entries = payload if isinstance(payload, list) else [payload]
        for e in entries:
            redact(e)
        with open(LOGFILE, "a") as fh:
            for e in entries:
                fh.write(json.dumps(e) + "\n")
        # Serialized so concurrent log POSTs cannot interleave their lines.
        with _lock:
            for e in entries:
                try:
                    render(e)
                except Exception as exc:
                    out(f"  (render error: {exc})")


if __name__ == "__main__":
    if "--keep" not in sys.argv:
        open(LOGFILE, "w").close()
    out(f"audit sink on :{PORT}   raw entries -> {LOGFILE}")
    out(f"{'time':8}  {'consumer':22} {'tool':24} {'':5} result")
    out("-" * 88)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
