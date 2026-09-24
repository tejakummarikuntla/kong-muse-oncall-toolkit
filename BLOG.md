---
title: Give Muse Code an On-Call Toolkit with Kong
published: false
tags: ai, webdev, architecture, tutorial
---

I wanted to find out whether a coding agent could do the first ten minutes of an incident investigation. Not fix anything. Just the part where you open four tabs, line up a deploy timeline against an error timeline, and work out which change to blame.

**Muse Code**, Meta's terminal coding agent, connects to remote MCP servers over `streamable_http`. So the tools are easy. The part that stopped me is in Meta's own documentation: MCP tools operate outside the sandbox and approval mechanisms. They run as unrestricted child processes or network connections.

That matters more than it sounds. You can set `shell_execute` and `file_write` to `ask` in your Muse settings and feel covered. Those settings do not put a prompt in front of an MCP tool call. If one of your MCP tools can roll back a production deployment, the agent can roll back a production deployment, and nothing in the client will stop it.

So the question was never "can the agent investigate". It was "where does the boundary go". I put it in front of the tools, at **Kong AI Gateway**, and gave the same agent two identities to prove it holds.

## What I evaluated first

I looked at writing a bespoke MCP server that checks a role on every handler. That works, and it means every permission decision lives in code I have to test, and the tool list is the same for everyone regardless of who is calling.

I looked at just putting the tools behind an API key. That is all or nothing. Anyone with the key gets every tool.

I went with Kong AI Gateway 2.0 because of one specific behavior: it converts an existing REST API into MCP tools, and it applies per-tool access control lists per identity, so `tools/list` itself is filtered. An investigator identity does not see a rollback tool. It cannot propose calling something it was never shown. That is a different property from "the call gets rejected", and I wanted both.

## The setup

```plaintext
  Muse Code                Kong AI Gateway 2.0              Ops REST API
 (MCP client)             (MCP server + ACLs)              (deploys, errors,
      |                            |                        runbooks, incidents)
      |  streamable_http           |                                |
      |  apikey: <identity>        |                                |
      +--------------------------->|                                |
      |                            |  per-tool ACL check            |
      |                            |  filter tools/list             |
      |                            |                                |
      |                            |  allowed: convert to REST      |
      |                            +------------------------------->|
      |                            |                                |
      |                            |  denied: 403, never forwarded  |
      |<---------------------------+                                |
      |                            |                                |
      |                            +---> http-log ---> audit sink    |
```

Kong AI Gateway sits between the agent and the operational APIs. It authenticates the caller, decides per tool whether that identity may use it, converts allowed calls into ordinary HTTP requests against the REST API, and writes an audit entry for every decision.

Two identities:

| Tool | `oncall-investigator` | `oncall-operator` |
| --- | --- | --- |
| `get-service-health` | visible | visible |
| `list-deployments` | visible | visible |
| `get-error-summary` | visible | visible |
| `get-error-samples` | visible | visible |
| `search-runbooks` | visible | visible |
| `get-runbook` | visible | visible |
| `create-incident` | visible | visible |
| `rollback-deployment` | **not visible** | visible |

Note that this is not a read versus write split. The investigator can write. It opens the incident. What it cannot do is change production. That distinction is the whole point, and a plain read-only key gets it wrong.

## Steps

- 🧰 Expose an existing ops REST API as MCP tools
- 🔑 Give each caller an identity
- 🚧 Set per-tool permissions so one tool disappears for one identity
- 🧾 Turn on the audit trail
- 🤖 Point Muse Code at it and run a real investigation
- ✅ Prove the boundary holds without the model in the loop

## Table of contents

- [Step 1: Convert the REST API into MCP tools](#step-1-convert-the-rest-api-into-mcp-tools)
- [Step 2: Give each caller an identity](#step-2-give-each-caller-an-identity)
- [Step 3: Set per-tool permissions](#step-3-set-per-tool-permissions)
- [Step 4: Turn on the audit trail](#step-4-turn-on-the-audit-trail)
- [Step 5: Point Muse Code at it](#step-5-point-muse-code-at-it)
- [Step 6: Prove it without the model](#step-6-prove-it-without-the-model)
- [Things I ran into](#things-i-ran-into)
- [Where I would take this next](#where-i-would-take-this-next)

## Step 1: Convert the REST API into MCP tools

The ops API is an ordinary REST service. Deployments, error summaries, error samples, runbooks, incidents. Kong's `conversion-listener` maps each endpoint to an MCP tool, so I did not write an MCP server at all.

```yaml
ai_gateway_mcp_servers:
  - ref: oncall-mcp
    ai_gateway: !lookup {id: !env AI_GATEWAY_ID}
    name: oncall-mcp
    display_name: "On-call toolkit"
    type: conversion-listener
    enabled: true
    config:
      url: http://host.docker.internal:9110/v1
      route:
        paths:
          - /ops-mcp
    tools:
      - name: get-error-summary
        description: >-
          Error counts for a service in five-minute buckets, broken down by
          error type. Use this to find the exact onset time and to see which
          error type is actually growing rather than which is merely loudest.
        method: GET
        path: /ops-mcp/errors/summary
        annotations:
          read_only_hint: true
          idempotent_hint: true
        parameters:
          - name: service
            in: query
            required: false
            schema:
              type: string
            description: Service name. Defaults to "checkout".
          - name: minutes
            in: query
            required: false
            schema:
              type: integer
            description: Window length in minutes. Defaults to 60.
```

Two things here are easy to get wrong.

The tool `path` must include the route prefix. Route `/ops-mcp` plus `url: .../v1` plus tool path `/ops-mcp/errors/summary` resolves to `http://host:9110/v1/errors/summary`. If you write `path: /errors/summary` you get a 404.

The `description` is not decoration. It is the only thing the agent reads when deciding which tool to reach for. I wrote each one as an instruction to a colleague, including when to use it, and the quality of the investigation moved noticeably.

## Step 2: Give each caller an identity

```yaml
ai_gateway_auth_strategies:
  - ref: oncall-key-auth
    ai_gateway: !lookup {id: !env AI_GATEWAY_ID}
    name: oncall-key-auth
    display_name: "On-call Key Auth"
    type: key-auth
    config:
      key_names:
        - apikey
      key_in_header: true
      hide_credentials: true

ai_gateway_consumers:
  - ref: oncall-investigator
    ai_gateway: !lookup {id: !env AI_GATEWAY_ID}
    name: oncall-investigator
    display_name: "On-call Investigator"
    type: api-key
    credentials:
      - ref: oncall-investigator-key
        ai_gateway_consumer: !ref oncall-investigator#id
        name: oncall-investigator-key
        display_name: "On-call Investigator Key"
        type: api-key
        api_key: !secret {source: !env INVESTIGATOR_KEY}

ai_gateway_consumer_groups:
  - ref: incident-response
    ai_gateway: !lookup {id: !env AI_GATEWAY_ID}
    name: incident-response
    display_name: "Incident Response"
    consumers:
      - !ref oncall-investigator#name
```

The operator is the same shape, in a group called `sre-oncall`. Write-only fields like `api_key` need `!secret`, not a plain string.

## Step 3: Set per-tool permissions

A baseline on the server, then an override on the one tool that changes production.

```yaml
    access:
      acl_attribute_type: consumer
      auth_strategies:
        - !ref oncall-key-auth#name
      default_tool_acls:
        allow:
          - incident-response
          - sre-oncall
```

```yaml
      - name: rollback-deployment
        description: >-
          Roll a service back to the deployment that preceded the one named.
          This changes production. Only run it when a runbook calls for it and
          an incident is already open.
        method: POST
        path: /ops-mcp/deployments/{deployment_id}/rollback
        annotations:
          destructive_hint: true
          idempotent_hint: false
        access:
          acls:
            allow:
              - sre-oncall
        parameters:
          - name: deployment_id
            in: path
            required: true
            schema:
              type: string
            description: The deployment to roll back. It must currently be live.
```

`acl_attribute_type` is required whenever you set `access`. Leave it out and the apply is rejected.

A per-tool ACL fully replaces `default_tool_acls` rather than merging with it. `rollback-deployment` lists only `sre-oncall`, so `incident-response` loses it. On `create-incident` I had to restate both groups for exactly this reason.

Apply it:

```bash
kongctl apply -f oncall-gateway.yaml --region in
```

Use `apply`, not `sync`. `apply` only creates and updates. `sync` reconciles every resource type named in the file, which means it deletes entities of those types that are not in your file.

## Step 4: Turn on the audit trail

```yaml
    config:
      logging:
        audits: true
        payloads: true
```

```yaml
ai_gateway_policies:
  - ref: oncall-audit-log
    ai_gateway: !lookup {id: !env AI_GATEWAY_ID}
    name: oncall-audit-log
    display_name: "On-call audit log"
    type: http-log
    enabled: true
    global: false
    config:
      http_endpoint: http://host.docker.internal:9111
      method: POST
```

I pointed `http-log` at a small local sink that prints the interesting fields. Every line below came from Kong.

## Step 5: Point Muse Code at it

Muse Code reads `~/.config/muse/settings.json`:

```json
{
  "schema_version": 1,
  "provider": "meta",
  "model": "muse-spark-1.3-contributor",
  "mcp_servers": {
    "oncall": {
      "transport": "streamable_http",
      "url": "http://localhost:8000/ops-mcp",
      "headers": {
        "apikey": "inv_your_investigator_key"
      },
      "enabled": true,
      "mode": "required"
    }
  }
}
```

Then the prompt an on-call engineer would actually type:

```bash
muse exec "Checkout errors increased after the last deployment. Investigate why, using the on-call tools available to you. Show the evidence for your conclusion, then tell me what should be done about it."
```

Nothing in that prompt names a tool, a service version, or a cause. Here is what came back, unedited:

```plaintext
Conclusion: the last checkout deployment `dep-482` caused the spike.

Evidence:

- `checkout` is degraded since `2026-09-24T16:58:46Z`: error rate 8.4% vs SLO
  0.5%, p99 4180ms vs baseline 310ms, live version `2026.9.24-3`.
- Last deployment is `dep-482` at `16:55:46Z` — `2026.9.24-3`, "checkout: reuse
  pooled connections for payments client" — ~3 min before degradation started.
- Error breakdown: `PaymentProviderTimeout` was 0/5min before, then 125 in
  `16:56:46-17:01:46Z`, rising to sustained 235/5min (1500 total). Other types
  flat: `CardDeclined` ~55-60, `CartValidationError` 15, `SessionExpired` 10.
- Samples on `2026.9.24-3`: "payments client: pool exhausted, waited 3000ms for
  a free connection", `pool_max_size: 8, pool_active: 8, pool_idle: 0`, stack
  `PaymentsClient.acquire (payments/pool.js:114)`.
- Dependency ruled out: `payments-provider-api` healthy, error 0.1% vs SLO 1.0%,
  p99 288ms vs baseline 275ms.
- Runbook `rb-204` "Payment provider timeouts in checkout": timeouts here almost
  always mean pool saturation, not provider down; if a deploy landed within
  ~10 min of onset, treat it as cause.

Incident opened: `INC-1001` (sev2).

What should be done, per `rb-204`:

1. Roll back `checkout` from `dep-482` to `dep-481` first, debug afterwards.
   Rollback is safe/idempotent.
2. Do not hot-patch pool sizing under load — a saturated pool does not recover
   on its own while traffic continues.
3. Do not page `#payments-oncall` / fail open to queued-authorization — that
   path is only if provider latency is elevated, and it is not.
```

The step I care about most is "dependency ruled out". The runbook says to check the provider before blaming it, and the agent checked the provider before blaming it. It also declined the escalation path on the grounds that its precondition was not met.

And here is Kong's record of that same run:

```plaintext
time      consumer              tool                     result
17:31:47  oncall-investigator   initialize                     HTTP 200   6ms
17:31:47  oncall-investigator   (tool list)              ALLOW HTTP 200   group incident-response
17:31:52  oncall-investigator   get-error-summary        ALLOW HTTP 200   group incident-response
17:31:52  oncall-investigator   list-deployments         ALLOW HTTP 200   group incident-response
17:31:52  oncall-investigator   get-service-health       ALLOW HTTP 200   group incident-response
17:31:57  oncall-investigator   get-service-health       ALLOW HTTP 200   group incident-response
17:31:57  oncall-investigator   get-error-samples        ALLOW HTTP 200   group incident-response
17:31:57  oncall-investigator   search-runbooks          ALLOW HTTP 200   group incident-response
17:32:05  oncall-investigator   get-runbook              ALLOW HTTP 200   group incident-response
17:32:23  oncall-investigator   create-incident          ALLOW HTTP 200   group incident-response
```

Ten tool calls, every one allowed, and no `rollback-deployment` anywhere. The agent recommended a rollback in prose and never attempted the call, because Kong never showed it the tool.

Now the same binary, same prompt style, operator key:

```bash
muse exec "Incident INC-1001 is open for the checkout service. Read the incident and runbook rb-204, confirm from the evidence whether a rollback is justified, and if it is, perform the rollback and report the result."
```

```plaintext
Rollback justified and completed.

Action: rolled back `dep-482` -> `dep-481` (version 2026.9.24-2) under `INC-1001`.
Result: `status: completed`, `rollback_id: rb-912229ed`, `restored: dep-481`,
completed 2026-09-24T17:33:55Z. Checkout health now `recovering`.
```

```plaintext
17:33:26  oncall-operator       (tool list)              ALLOW HTTP 200   group sre-oncall
17:33:39  oncall-operator       get-service-health       ALLOW HTTP 200   group sre-oncall
17:33:39  oncall-operator       get-runbook              ALLOW HTTP 200   group sre-oncall
17:33:39  oncall-operator       list-deployments         ALLOW HTTP 200   group sre-oncall
17:33:42  oncall-operator       get-error-samples        ALLOW HTTP 200   group sre-oncall
17:33:55  oncall-operator       rollback-deployment      ALLOW HTTP 200   group sre-oncall
17:33:57  oncall-operator       get-service-health       ALLOW HTTP 200   group sre-oncall
```

Same endpoint, same agent, different key. The eighth tool appears and works.

## Step 6: Prove it without the model

Tool filtering stops a cooperative agent from trying. It is not a security boundary on its own, because a client can call a tool name it was never offered. So I wrote a script that speaks the MCP handshake directly and deliberately calls `rollback-deployment` with the investigator key.

```plaintext
[anonymous] no credential
  PASS  anonymous -> 401

[investigator] key in group incident-response
  PASS  tools/list shows 7 tools
  PASS  rollback-deployment absent from tools/list
  PASS  get-service-health -> degraded
  PASS  create-incident -> allowed          | incident=INC-1001
  PASS  rollback-deployment -> 403

[operator] key in group sre-oncall
  PASS  tools/list shows 8 tools
  PASS  rollback-deployment -> completed    | restored=dep-481

[audit] Kong's http-log output
  PASS  exactly one deny recorded
  PASS  deny names the caller               | oncall-investigator (identifier=username)
  PASS  denied call never reached the ops API | upstream_status='' proxy_latency=-1
  PASS  same tool allowed for sre-oncall

16/16 passed
```

The denial record is worth looking at directly:

```json
"ai": {
  "mcp": {
    "audit": [
      {
        "primitive_name": "rollback-deployment",
        "primitive": "tool",
        "consumer": { "name": "oncall-investigator", "identifier": "username" },
        "action": "deny"
      }
    ]
  }
},
"upstream_status": "",
"latencies": { "proxy": -1 }
```

`upstream_status` is empty and `latencies.proxy` is -1. Kong never opened a connection to the ops API. The refusal happened at the gateway, and the ops API has no record that anyone tried.

That is two layers doing two different jobs. Filtering keeps the agent from forming the intent. The ACL handles the client that forms it anyway.

## Things I ran into

**Environment variables do not interpolate into MCP headers.** The Muse docs describe `${VAR}` interpolation. In Muse Code 1.3.0 it did not apply to MCP header values. My config sent the literal string `${INVESTIGATOR_KEY}`, Kong returned 401, and Muse reported this:

```plaintext
Required MCP server `oncall` failed during startup: it requires an
OAuth sign-in; run `muse mcp login oncall` and restart.
```

There is no OAuth anywhere in this setup. Muse turns any 401 into an OAuth prompt, which sends you a long way in the wrong direction. Putting the literal key in the file connected immediately. If you hit that error against a key-auth server, check the header value before you touch OAuth.

**There is no `--settings` flag.** Muse reads `~/.config/muse/settings.json` and nothing else. To run two identities without overwriting my real config, I used `XDG_CONFIG_HOME`, which it does respect:

```bash
XDG_CONFIG_HOME=/tmp/muse-investigator muse exec "..."
```

Copy `auth.json` and `trust.json` into that directory alongside your `settings.json` or the run will not authenticate.

**Test the wiring with the echo provider.** `muse exec --provider echo "ping"` starts the session and connects every MCP server with `mode: required`, but never calls the model. Every configuration mistake above was found this way, at zero cost.

**Request bodies collapse into one argument.** Path and query parameters get prefixed, so `deployment_id` in a path becomes `path_deployment_id` and `service` in a query becomes `query_service`. A request body does not get expanded into named arguments at all. It arrives as a single `body` object. Check `tools/list` before you assume an argument name.

**The `request_body` shape is not in the docs.** The reference says tools accept `request_body` in OpenAPI JSON format and gives no example. The OpenAPI 3 `requestBody` object works:

```yaml
        request_body:
          required: true
          content:
            application/json:
              schema:
                type: object
                required: [title]
                properties:
                  title:
                    type: string
```

**`hide_credentials` does not apply to the log.** I had `hide_credentials: true` on the auth strategy, which strips the key from the request Kong forwards upstream. The `http-log` payload still contains the headers the *client* sent, raw key included. I found 26 copies of a working API key sitting in my log file. If you forward `http-log` to a hosted log service, that is where your keys end up. Scrub the sensitive headers at the sink, or before the sink:

```python
SENSITIVE_HEADERS = ("apikey", "authorization", "x-api-key", "cookie")

def redact(entry):
    for section in ("request", "response"):
        headers = (entry.get(section) or {}).get("headers")
        if isinstance(headers, dict):
            for h in list(headers):
                if h.lower() in SENSITIVE_HEADERS:
                    headers[h] = "<redacted>"
```

**An allow and a deny log different subjects.** An allow records the consumer group that granted access, with `identifier: consumer_group`. A deny records the calling consumer, with `identifier: username`, because no group matched. If you are building alerts on this, do not assume one field shape.

**Each allowed tool produces two log entries.** One for the MCP call, one for the loopback HTTP request Kong makes to your REST API. They share no correlation id and the loopback is flushed first, so you cannot pair them by arrival order. I tried, and it confidently attached the wrong upstream call to the wrong tool. The `upstream_status` field on the MCP entry is the reliable signal.

## Where I would take this next

- **Make `create-incident` idempotent.** Across runs the agent sometimes called it twice. An idempotency key on the tool, or a dedupe on the API, would stop duplicate incidents during a retry.
- **Scope the operator key to an open incident.** Right now `sre-oncall` can roll back anything at any time. Requiring a matching open incident would tie the permission to a live situation instead of a standing grant.
- **Time-box the grant.** A key that carries the rollback tool only during an active page is a much smaller blast radius than a permanent one.
- **Route the model side through Kong too.** Muse has a `--base-url` flag that overrides the Meta provider endpoint, and Kong models accept an `upstream_url`, so the model traffic could run through the same gateway that holds the tools. I have not built that yet. It would put token spend and prompt content under the same control point as the actions.
- **Add rate limits per identity.** An agent in a retry loop against a real deploy API is its own kind of incident.

## The part worth stealing

The reusable shape is not the checkout scenario. It is this: your existing REST API already encodes operations at different risk levels, and an agent does not need all of them at once.

Take any internal API you already run. Split its endpoints into diagnostics, safe writes, and production changes. Give the agent's identity the first two. Put the third behind a different identity. Then check the audit log for the tools it never got to call.

The thing that surprised me was how much the agent could conclude without any ability to act. It produced a complete, evidence-backed diagnosis with a specific recommendation, and the recommendation was correct. Withholding the destructive tool cost nothing in diagnostic quality.

If you try this on your own ops API, I would like to know which endpoint you found hardest to classify. The diagnostics were obvious and the destructive ones were obvious. It was the middle tier, the writes that are safe until they are not, where I kept changing my mind.
