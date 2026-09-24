#!/usr/bin/env python3
"""
Mock operations API for the "on-call toolkit" demo.

Stands in for the four systems an on-call engineer actually opens during an
incident: a deploy tracker, an error aggregator, a runbook store, and an
incident tracker. Kong turns these REST endpoints into MCP tools.

The incident is seeded relative to process start, so the data always looks
live. The root cause is *discoverable* - nothing in any single response names
it. An agent has to correlate the deploy timeline against the error timeline,
then read the matching runbook.

    python3 opsapi.py          # serves on :9110 under /v1
"""

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 9110

# ---------------------------------------------------------------- seed clock

BOOT = datetime.now(timezone.utc).replace(microsecond=0)


def ago(minutes: int) -> datetime:
    return BOOT - timedelta(minutes=minutes)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# The bad deploy. Everything downstream is derived from this offset so the
# correlation stays exact no matter when the process starts.
BAD_DEPLOY_MIN = 36          # checkout deploy that introduced the regression
ERROR_ONSET_MIN = 33         # errors start climbing 3 min after the rollout

# ---------------------------------------------------------------- fixtures

DEPLOYMENTS = [
    {
        "id": "dep-482",
        "service": "checkout",
        "version": "2026.9.24-3",
        "commit": "a3f21c8",
        "author": "priya.raman",
        "summary": "checkout: reuse pooled connections for payments client",
        "deployed_at": iso(ago(BAD_DEPLOY_MIN)),
        "status": "live",
        "rollback_target": "dep-481",
    },
    {
        "id": "dep-481",
        "service": "checkout",
        "version": "2026.9.24-2",
        "commit": "7c09b41",
        "author": "marcus.oyelaran",
        "summary": "checkout: add idempotency key to refund endpoint",
        "deployed_at": iso(ago(372)),
        "status": "superseded",
        "rollback_target": "dep-478",
    },
    {
        "id": "dep-480",
        "service": "search",
        "version": "2026.9.24-1",
        "commit": "e51aa90",
        "author": "dana.whitfield",
        "summary": "search: bump opensearch client to 3.4.1",
        "deployed_at": iso(ago(19)),
        "status": "live",
        "rollback_target": "dep-melt",
    },
    {
        "id": "dep-478",
        "service": "checkout",
        "version": "2026.9.23-7",
        "commit": "b8142de",
        "author": "priya.raman",
        "summary": "checkout: emit cart_abandoned analytics event",
        "deployed_at": iso(ago(1490)),
        "status": "superseded",
        "rollback_target": None,
    },
]

# Per-minute error counts, bucketed into 5-minute windows. Before the onset the
# service has a low, boring baseline. After it, one error type takes off while
# the others stay flat - so "what changed" has exactly one answer.
ERROR_TYPES = {
    "PaymentProviderTimeout": {"baseline": 0, "spike": 47},
    "CardDeclined": {"baseline": 11, "spike": 12},
    "CartValidationError": {"baseline": 3, "spike": 3},
    "SessionExpired": {"baseline": 2, "spike": 2},
}

SAMPLES = {
    "PaymentProviderTimeout": [
        {
            "timestamp": iso(ago(ERROR_ONSET_MIN - 2)),
            "service": "checkout",
            "version": "2026.9.24-3",
            "message": "payments client: pool exhausted, waited 3000ms for a free connection",
            "context": {
                "pool_max_size": 8,
                "pool_active": 8,
                "pool_idle": 0,
                "wait_timeout_ms": 3000,
                "upstream": "payments-provider-api",
            },
            "stack": [
                "at PaymentsClient.acquire (payments/pool.js:114)",
                "at PaymentsClient.authorize (payments/client.js:61)",
                "at CheckoutService.submit (checkout/service.js:203)",
            ],
        },
        {
            "timestamp": iso(ago(ERROR_ONSET_MIN - 9)),
            "service": "checkout",
            "version": "2026.9.24-3",
            "message": "payments client: pool exhausted, waited 3000ms for a free connection",
            "context": {
                "pool_max_size": 8,
                "pool_active": 8,
                "pool_idle": 0,
                "wait_timeout_ms": 3000,
                "upstream": "payments-provider-api",
            },
            "stack": [
                "at PaymentsClient.acquire (payments/pool.js:114)",
                "at PaymentsClient.authorize (payments/client.js:61)",
                "at CheckoutService.submit (checkout/service.js:203)",
            ],
        },
    ],
    "CardDeclined": [
        {
            "timestamp": iso(ago(12)),
            "service": "checkout",
            "version": "2026.9.24-3",
            "message": "issuer declined authorization (code 51, insufficient funds)",
            "context": {"provider_code": "51", "retryable": False},
            "stack": [],
        }
    ],
}

RUNBOOKS = [
    {
        "id": "rb-204",
        "title": "Payment provider timeouts in checkout",
        "symptoms": ["PaymentProviderTimeout", "pool exhausted", "checkout 5xx"],
        "services": ["checkout"],
        "body": (
            "## Payment provider timeouts\n\n"
            "Checkout holds a bounded connection pool to the payments provider. "
            "Timeouts here almost always mean the pool is saturated, not that the "
            "provider is down. Confirm provider health before blaming it.\n\n"
            "### Triage\n"
            "1. Check the provider status page and `payments-provider-api` latency. "
            "If provider p99 is normal, the fault is ours.\n"
            "2. List deployments to `checkout` in the last 60 minutes.\n"
            "3. If a deployment landed within ~10 minutes of error onset, treat it "
            "as the cause.\n\n"
            "### Resolution\n"
            "**If the onset correlates with a deployment, roll back first and debug "
            "afterwards.** A saturated pool does not recover on its own while traffic "
            "continues; every queued request consumes a worker. Pool sizing changes "
            "must not be hot-patched under load.\n\n"
            "Rolling back checkout is safe and idempotent. Open an incident before "
            "the rollback so the timeline is captured.\n\n"
            "### Escalation\n"
            "If provider latency *is* elevated, do not roll back. Page "
            "`#payments-oncall` and fail open to the queued-authorization path."
        ),
    },
    {
        "id": "rb-118",
        "title": "Search cluster degradation",
        "symptoms": ["SearchTimeout", "opensearch", "shard unavailable"],
        "services": ["search"],
        "body": (
            "## Search degradation\n\n"
            "Check shard allocation and the opensearch client version. Rolling "
            "restarts are safe; reindexing is not."
        ),
    },
]

SERVICE_HEALTH = {
    "checkout": {
        "service": "checkout",
        "status": "degraded",
        "error_rate_pct": 8.4,
        "error_rate_slo_pct": 0.5,
        "p99_latency_ms": 4180,
        "p99_latency_baseline_ms": 310,
        "requests_per_min": 560,
        "live_version": "2026.9.24-3",
        "degraded_since": iso(ago(ERROR_ONSET_MIN)),
    },
    "search": {
        "service": "search",
        "status": "healthy",
        "error_rate_pct": 0.2,
        "error_rate_slo_pct": 0.5,
        "p99_latency_ms": 240,
        "p99_latency_baseline_ms": 220,
        "requests_per_min": 1900,
        "live_version": "2026.9.24-1",
        "degraded_since": None,
    },
    "payments-provider-api": {
        "service": "payments-provider-api",
        "status": "healthy",
        "error_rate_pct": 0.1,
        "error_rate_slo_pct": 1.0,
        "p99_latency_ms": 288,
        "p99_latency_baseline_ms": 275,
        "requests_per_min": 540,
        "live_version": "n/a (third party)",
        "degraded_since": None,
    },
}

# Mutable state
INCIDENTS: list[dict] = []
ROLLBACKS: list[dict] = []


# ---------------------------------------------------------------- derived

def error_summary(service: str, minutes: int) -> dict:
    """Five-minute buckets over the requested window, newest last."""
    buckets = []
    span = max(5, minutes)
    start = BOOT - timedelta(minutes=span)
    n = span // 5
    for i in range(n):
        b_start = start + timedelta(minutes=5 * i)
        b_end = b_start + timedelta(minutes=5)
        # A bucket is "after onset" if any part of it falls past the onset time,
        # so the spike shows up in the first window that contains it.
        minutes_ago = (BOOT - b_end).total_seconds() / 60
        spiking = service == "checkout" and minutes_ago < ERROR_ONSET_MIN
        counts = {}
        for name, cfg in ERROR_TYPES.items():
            if service != "checkout":
                counts[name] = 0
                continue
            per_min = cfg["spike"] if spiking else cfg["baseline"]
            # PaymentProviderTimeout ramps rather than stepping, which is what a
            # saturating pool actually looks like.
            if spiking and name == "PaymentProviderTimeout":
                ramp = min(1.0, (ERROR_ONSET_MIN - minutes_ago + 5) / 15)
                per_min = int(per_min * max(0.15, ramp))
            counts[name] = per_min * 5
        buckets.append(
            {
                "window_start": iso(b_start),
                "window_end": iso(b_end),
                "counts": counts,
                "total": sum(counts.values()),
            }
        )
    totals: dict[str, int] = {}
    for b in buckets:
        for k, v in b["counts"].items():
            totals[k] = totals.get(k, 0) + v
    return {
        "service": service,
        "window_minutes": span,
        "generated_at": iso(BOOT),
        "totals_by_type": totals,
        "buckets": buckets,
    }


# ---------------------------------------------------------------- routing

ROUTES: list[tuple[str, re.Pattern, str]] = []


def route(method: str, pattern: str):
    rx = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern) + "$")

    def wrap(fn):
        ROUTES.append((method, rx, fn.__name__))
        globals()["_h_" + fn.__name__] = fn
        return fn

    return wrap


@route("GET", "/v1/services/{service}/health")
def get_health(q, body, service):
    h = SERVICE_HEALTH.get(service)
    return (200, h) if h else (404, {"error": f"unknown service '{service}'"})


@route("GET", "/v1/deployments")
def list_deployments(q, body):
    svc = q.get("service")
    limit = int(q.get("limit", 20))
    rows = [d for d in DEPLOYMENTS if not svc or d["service"] == svc]
    rows.sort(key=lambda d: d["deployed_at"], reverse=True)
    return 200, {"deployments": rows[:limit], "count": len(rows[:limit])}


@route("GET", "/v1/errors/summary")
def get_error_summary(q, body):
    svc = q.get("service", "checkout")
    minutes = int(q.get("minutes", 60))
    return 200, error_summary(svc, minutes)


@route("GET", "/v1/errors/samples")
def get_error_samples(q, body):
    etype = q.get("type")
    limit = int(q.get("limit", 5))
    if not etype:
        return 400, {"error": "query parameter 'type' is required"}
    rows = SAMPLES.get(etype, [])
    return 200, {"error_type": etype, "samples": rows[:limit], "count": len(rows[:limit])}


@route("GET", "/v1/runbooks")
def search_runbooks(q, body):
    term = (q.get("q") or "").lower()
    rows = [
        r
        for r in RUNBOOKS
        if not term
        or term in r["title"].lower()
        or any(term in s.lower() for s in r["symptoms"])
        or any(term in s.lower() for s in r["services"])
    ]
    # Search results omit the body; the agent must fetch the runbook to read it.
    return 200, {
        "runbooks": [
            {k: v for k, v in r.items() if k != "body"} for r in rows
        ],
        "count": len(rows),
    }


@route("GET", "/v1/runbooks/{runbook_id}")
def get_runbook(q, body, runbook_id):
    for r in RUNBOOKS:
        if r["id"] == runbook_id:
            return 200, r
    return 404, {"error": f"unknown runbook '{runbook_id}'"}


@route("POST", "/v1/incidents")
def create_incident(q, body):
    title = (body or {}).get("title")
    if not title:
        return 400, {"error": "field 'title' is required"}
    inc = {
        "id": f"INC-{1000 + len(INCIDENTS) + 1}",
        "title": title,
        "service": (body or {}).get("service", "unknown"),
        "severity": (body or {}).get("severity", "sev3"),
        "summary": (body or {}).get("summary", ""),
        "status": "open",
        "created_at": iso(datetime.now(timezone.utc)),
        "created_by": "mcp-client",
    }
    INCIDENTS.append(inc)
    return 201, inc


@route("GET", "/v1/incidents")
def list_incidents(q, body):
    return 200, {"incidents": INCIDENTS, "count": len(INCIDENTS)}


@route("POST", "/v1/deployments/{deployment_id}/rollback")
def rollback_deployment(q, body, deployment_id):
    dep = next((d for d in DEPLOYMENTS if d["id"] == deployment_id), None)
    if not dep:
        return 404, {"error": f"unknown deployment '{deployment_id}'"}
    if dep["status"] != "live":
        return 409, {"error": f"deployment '{deployment_id}' is not live"}
    if not dep["rollback_target"]:
        return 409, {"error": "no rollback target recorded"}
    target = next((d for d in DEPLOYMENTS if d["id"] == dep["rollback_target"]), None)
    rb = {
        "rollback_id": f"rb-{uuid.uuid4().hex[:8]}",
        "service": dep["service"],
        "rolled_back": dep["id"],
        "restored": dep["rollback_target"],
        "restored_version": target["version"] if target else "unknown",
        "incident_ref": (body or {}).get("incident_ref"),
        "reason": (body or {}).get("reason", ""),
        "status": "completed",
        "completed_at": iso(datetime.now(timezone.utc)),
    }
    dep["status"] = "rolled-back"
    if target:
        target["status"] = "live"
    SERVICE_HEALTH[dep["service"]]["status"] = "recovering"
    ROLLBACKS.append(rb)
    return 200, rb


# ---------------------------------------------------------------- server

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print(f"  ops-api  {self.command:4} {self.path}  -> {args[1]}")

    def _dispatch(self, method):
        path, _, raw_q = self.path.partition("?")
        q = {}
        for pair in raw_q.split("&"):
            if "=" in pair:
                k, _, v = pair.partition("=")
                q[k] = v.replace("%20", " ").replace("+", " ")

        body = None
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            try:
                body = json.loads(self.rfile.read(n))
            except json.JSONDecodeError:
                return self._send(400, {"error": "malformed JSON body"})

        for m, rx, fname in ROUTES:
            if m != method:
                continue
            match = rx.match(path)
            if match:
                fn = globals()["_h_" + fname]
                status, payload = fn(q, body, **match.groupdict())
                return self._send(status, payload)
        self._send(404, {"error": f"no route for {method} {path}"})

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _send(self, status, payload):
        raw = json.dumps(payload, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


if __name__ == "__main__":
    print(f"ops-api listening on http://0.0.0.0:{PORT}/v1")
    print(f"  incident seeded: checkout dep-482 at {iso(ago(BAD_DEPLOY_MIN))} "
          f"({BAD_DEPLOY_MIN}m ago), errors from {iso(ago(ERROR_ONSET_MIN))}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
