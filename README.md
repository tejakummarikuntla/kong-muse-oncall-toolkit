# On-call toolkit for Muse Code, gated by Kong AI Gateway

A working demo for the post *Give Muse Code an On-Call Toolkit with Kong*.

An ops REST API is converted into eight MCP tools by **Kong AI Gateway 2.0**.
Two identities get two different toolsets. An investigator can diagnose a
production incident and open an incident record, but cannot roll back a
deployment. An operator can. The refusal happens at the gateway, and both the
allow and the deny are recorded in an audit log.

## Layout

```
oncall-gateway.yaml              8 tools, 2 identities, per-tool ACLs, http-log
ops-api/opsapi.py                mock ops API, seeds a live incident on start
ops-api/auditsink.py             receives Kong's http-log, renders ACL decisions
proof/verify.py                  16 assertions, no model in the loop
muse/settings.*.json             Muse MCP config per identity
stack.sh                         bring Docker + containers + python services up
demo.sh                          up | verify | muse-config | reset | down
keepalive.sh                     keeps Docker Desktop's VM from idling out
.env                             gateway id, region, generated keys
```

## Prerequisites

- A Kong Konnect AI Gateway (hybrid) with a running data plane on `:8000`
- `kongctl` authenticated: `kongctl login`
- Python 3.10+
- Muse Code, only for the two agent runs: `curl -fsSL https://dev.meta.ai/install.sh | sh`

## Run it

```bash
set -a; source .env; set +a

./stack.sh          # docker daemon, containers, ops API, audit sink
./demo.sh up        # apply the gateway config
./demo.sh verify    # 16/16, proves the access model without Muse
```

`verify.py` is the one to run while iterating. It speaks the MCP handshake
directly, so it costs nothing and catches every configuration mistake.

For the agent runs:

```bash
./demo.sh muse-config     # writes per-identity configs, prints the commands
```

Test the wiring for free before spending a model call:

```bash
XDG_CONFIG_HOME=/tmp/muse-investigator muse exec --provider echo "ping"
```

The echo provider starts a session and connects every `mode: required` MCP
server, but never calls the model.

## What `verify.py` asserts

```
anonymous     401, no tool list
investigator  7 tools; rollback-deployment absent from tools/list;
              403 if called anyway; create-incident succeeds
operator      8 tools; rollback-deployment completes, restores dep-481
audit         deny recorded with the caller's name; upstream_status empty
              and proxy latency -1, so the ops API was never contacted
```

## Notes that cost time

- **`${VAR}` does not interpolate into MCP headers** in Muse Code 1.3.0. Put
  the literal key in `settings.json`. Kong's 401 gets reported by Muse as
  "requires an OAuth sign-in", which is misleading: there is no OAuth here.
- **Muse has no `--settings` flag.** It reads `$XDG_CONFIG_HOME/muse/settings.json`.
  Copy `auth.json` and `trust.json` into the same directory.
- **Tool `path` must include the route prefix.** `/ops-mcp/errors/summary`, not
  `/errors/summary`.
- **`access.acl_attribute_type` is required** whenever `access` is set.
- **A per-tool ACL replaces `default_tool_acls`**, it does not merge. Restate
  every group you still want.
- **Use `kongctl apply`, not `sync`.** `sync` deletes entities of any type named
  in your file that are not in your file.
- **Request bodies collapse into one `body` argument.** Path and query params
  are prefixed: `path_deployment_id`, `query_service`.
- **Docker Desktop's VM idles out** and takes the data plane with it.
  `keepalive.sh` holds it open; `stack.sh` recovers it if it drops.

## Resetting

`./demo.sh reset` restarts the ops API, which re-seeds the incident relative to
process start. Do this between agent runs, since a completed rollback leaves
`dep-482` in a non-live state and the next rollback returns 409.
