# Hook client latency

The hook command takes a short path through `yoke_cli.main` to the local
resident. Keep its imports separate from the command catalog, HTTP transport,
fallback evaluator and Stop safety bookkeeping. The resident owns the existing
HTTP connection pool; a normal warm hook reuses TLS connections. Configuration
and credentials are resolved for the caller, so updates and different machine
homes remain visible rather than being cached across requests.

Wheel ownership comes from the distribution's RECORD manifest. Match the
module's path before resolving its physical location; do not resolve every
other file in the manifest. The check still refuses an unrecorded module or
an import outside the owning distribution. Source-bound hooks do not need
`importlib.metadata`. Fallback client-wall reporting loads its machine config
and transport only when it reports; only Stop loads its circuit breaker.

## Resident observations

Profile `evaluate_inprocess` inside the resident's caller process context as
well as the short-lived command. Include real fact collection and inspect
subprocess calls, registry writes and transcript discovery. A mocked HTTP
answer separates client work from network time; it does not prove the
Production gap. Exercise concurrent calls and both missing and saved
transcripts, and preserve which discovery or ancestor selection was mocked.

A surface without liveness process names does not write an ambient anchor.
A failed named lookup also stops there; passing an absent anchor to the
shared registry would trigger a second, generic ancestry walk. Named ancestry
is cached for two seconds under the caller parent's PID, start token and
surface names. Recheck the parent's start token and any cached anchor's live
start token on reuse. Registry tenancy is always reread: a clean unchanged
record needs no write, while a changed transcript or contending session still
updates the record and runs the existing fail-closed checks.

Concurrent hooks share fleet process listings and Codex transcript path
discovery for at most two seconds. Failed listings prove nothing and are not
cached. Transcript caches include the roots and thread id, are bounded, and
never cache transcript contents or per-turn model/usage facts. Newly created
or moved transcripts become discoverable at the next refresh. Function calls
made during resident evaluation, including contender liveness, use that
request's existing HTTP pool; the context is isolated between threads and
cleared even when evaluation raises. HTTP status and redirect checks still
apply.

## Measure the command

From a claimed lane, capture imports once:

```sh
yoke dev run -- python3 -X importtime -c \
  'import yoke_cli.main; import yoke_cli.commands.adapters.hooks; import yoke_cli.hook_resident_client' \
  2> /tmp/hook-importtime.txt
```

Time the actual `yoke hook evaluate` command with a representative recorded
payload, the correct harness environment and an isolated machine home. Preserve
the output and exit code. Separate cold resident startup from warm calls, and
include the immutable CLI launcher's version/ownership check when measuring
installed clients. Do not treat a source checkout or a mocked socket as proof
of installed client performance. The entry-import regression test lists the
heavy dependencies that must stay out of the short-lived hook process.

## Production acceptance

Use the existing client-wall reports and `yoke sessions hook-overhead` to
inspect coverage and the harness/surface mix. The latter reports evaluator
time; its remainder is not the same as client time minus server wall time.
For that comparison, inspect paired `client_wall_ms` and `server_wall_ms`
from `HookDispatchTelemetry` with bounded `yoke events query` reads or a
diagnostic `yoke db read` aggregation. Add no telemetry for this measurement.

Confirm client update evidence first: a server release does not update already
installed clients. Measure three consecutive complete UTC days after client
adoption, requiring each day's median paired gap to be below 150ms. Report
sample counts, missing timing coverage, and harness/surface mix. Never average
hourly medians, substitute evaluator duration for server wall time, or count a
partial day. Missing observations leave acceptance pending; an observed gap at
or above the threshold requires more client work. Retain the post-deploy QA
obligation until this evidence passes.
