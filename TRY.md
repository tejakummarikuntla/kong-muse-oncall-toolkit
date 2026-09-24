# Try it yourself

All commands run from `Dev/content/muse-oncall-toolkit/`.

```bash
cd ~/Dev/content/muse-oncall-toolkit
./stack.sh          # docker, kong, ops API, audit sink
```

## 1. See the two toolsets (no agent, no model)

```bash
./try.sh tools investigator
./try.sh tools operator
./try.sh tools anonymous
```

The investigator gets 7 tools. The operator gets 8. Anonymous gets `HTTP 401`
before any tool is even considered. Same URL, same config, different key.

## 2. Call a tool by hand

```bash
./try.sh call investigator get-service-health '{"path_service":"checkout"}'
```

Note the argument name. Path parameters are prefixed `path_`, query parameters
`query_`, and a JSON body collapses into a single `body` object.

## 3. Try the thing the investigator is not allowed to do

```bash
./try.sh call investigator rollback-deployment '{"path_deployment_id":"dep-482"}'
```

`HTTP 403`. The tool was not in the investigator's list, and calling it by name
anyway does not work either.

Now the same call with the other key:

```bash
./try.sh call operator rollback-deployment \
  '{"path_deployment_id":"dep-482","body":{"reason":"rb-204"}}'
```

`HTTP 200`, and production actually changed:

```bash
curl -s "http://localhost:9110/v1/deployments?service=checkout&limit=2" \
  | jq -r '.deployments[] | "\(.id)  \(.status)"'
```

## 4. Watch Kong decide, live

In a second terminal:

```bash
tail -f /tmp/auditsink.log
```

Then re-run anything from above. Every line is Kong's own `http-log` output:
which consumer, which tool, allow or deny, and which rule granted it.

## 5. Run Muse Code against it

```bash
./demo.sh reset          # put dep-482 back to live
./demo.sh muse-config    # writes per-identity configs, prints the commands
```

Free wiring test first. The echo provider connects every MCP server but never
calls the model, so it costs nothing:

```bash
XDG_CONFIG_HOME=/tmp/muse-investigator muse exec --provider echo "ping"
```

Then the real investigation:

```bash
XDG_CONFIG_HOME=/tmp/muse-investigator muse exec --trust-workspace \
  "Checkout errors increased after the last deployment. Investigate why, using
   the on-call tools available to you. Show the evidence for your conclusion,
   then tell me what should be done about it."
```

The agent will diagnose the incident and recommend a rollback. It will not
attempt one. Check `/tmp/auditsink.log`: there is no `rollback-deployment` line,
because the tool was never in its list.

Then hand it to the operator:

```bash
XDG_CONFIG_HOME=/tmp/muse-operator muse exec --trust-workspace \
  "Incident INC-1001 is open for the checkout service. Read the incident and
   runbook rb-204, confirm from the evidence whether a rollback is justified,
   and if it is, perform the rollback and report the result."
```

Each full run costs roughly 10-15 requests against the Muse plan's 10-50 per
5 hours, so budget about one or two runs per window.

## 6. Prove the whole model at once

```bash
./demo.sh verify
```

16 assertions, no model involved. This is the one to run while changing config.

## Reset between runs

```bash
./demo.sh reset
```

A completed rollback leaves `dep-482` non-live, so a second rollback returns
`409`. Reset re-seeds the incident relative to process start.
