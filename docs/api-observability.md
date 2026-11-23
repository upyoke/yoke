# API observability

Hosted API processes export metrics as CloudWatch Embedded Metric Format
(EMF) JSON on `yoke.api.metrics` (stderr → the service log group). Local
installs stay instrumented with no exporter unless an OTLP endpoint or
console export is set. Self-hosted installs match local unless you opt
into the log sink.

## Metrics contract

Keep these identities stable:

- Namespace: `Yoke/API`
- CloudWatch dimension: `Environment` only (`deployment.environment`)
- Useful series: request counts, failures, and latency, plus process CPU
- Bounded attributes only: function, function version, outcome, HTTP
  method/target/status, hook event name. Request IDs, session IDs, and
  other correlation identifiers never become metric attributes, including
  during debugging.

Counters and histograms export **delta** values every 60s. Each EMF line
is the increment since the last export, not a replay of every historical
series. A process restart starts counts from zero. CloudWatch still sums
those deltas; do not treat OTel attribute cardinality as CloudWatch
dimension cardinality.

`YOKE_OTEL_LOG_METRICS=1` turns the log sink on; without it the sink is
off. An environment that declares `observability.emit_log_metrics: true`
(hosted prod and stage do) gets the flag in its container env file on
every core-container deploy. The deploy then reads the new container's
`ObservabilityConfigured` startup records and fails, without rolling
back, unless every process reports `otel_reason` `exporting:log`; a
silent `instrumented_no_exporter` would drop every `Yoke/API` metric.
Local and self-hosted runs set the flag by hand when they want EMF.

## Targeted diagnostics

Metrics stay bounded. Correlation lives on structured logs, traces, and
control-plane events. Capture is gated in-process by a campaign on the
existing `YOKE_API_*` env family — not by filtering historical reads.

Set all three (until is required; missing or past until is off):

```bash
YOKE_API_DEBUG_SCOPE=function:items.get.run   # or session:<id> | request:<id> | service:<name>
YOKE_API_DEBUG_UNTIL=2026-09-16T22:00:00Z     # ISO-8601; auto-expires, no restart
YOKE_API_DEBUG_MAX_RECORDS=200                # default 200, cap 2000
```

While the campaign is live, matching DEBUG records emit (including one
`FunctionDispatchDebug` log per in-scope dispatch) with `request_id` /
`session_id` / `function`. Enforcement lives on the JSON log handler, so
child loggers such as `yoke.api.dispatch` cannot bypass it. Root stays at
`YOKE_API_LOG_LEVEL` (INFO by default); the campaign does not enable
unrelated libraries' DEBUG output. After `UNTIL` or the record cap, capture
stops even if the process keeps running. Unmatched DEBUG is dropped.
INFO/ERROR logs and metrics are unchanged. Campaign env never becomes a
metric attribute.

Producers that want extra payload call the same gate, default off. The
dispatcher is the live one: `YokeFunctionCalled` carries only the result's
byte count and checksum routinely, and copies the full result document
onto the event while a matching campaign is live. Budget accordingly — an
in-scope dispatch spends two records, the `FunctionDispatchDebug` log and
the result capture, so a 200-record campaign covers about 100 dispatches:

```python
from yoke_core.api.observability import debug_detail_allowed

if debug_detail_allowed({
    "function": function_id,
    "session_id": session_id,
    "request_id": request_id,
    "service": service_name(),
}):
    ...  # copy bounded extra detail
```

Call it once per unit of work: a true answer consumes a record, so a
speculative call spends budget on detail nobody records.

`YOKE_API_LOG_LEVEL=DEBUG` without a campaign remains the local
restart-to-clear path. Do not leave it on in hosted processes.

Query windows still help read what was captured. Select the hosting project
whose `aws-admin` capability owns access; the adapter materializes credentials
only for the AWS subprocess:

```bash
yoke aws exec --project <hosting-project> -- logs filter-log-events \
  --log-group-name /yoke/<env>/core \
  --start-time <epoch-ms> --end-time <epoch-ms> \
  --filter-pattern '"<request-id-or-session-id>"'
yoke events query --session <session-id> --since '<start>' --until '<end>' --limit 100
```

OTLP traces: set `OTEL_EXPORTER_OTLP_ENDPOINT`. Hosted EMF mode does not
export spans.

## Related flags

| Flag | Effect |
| --- | --- |
| `YOKE_ENVIRONMENT` / `APP_ENV` | Resource environment name (identity only) |
| `YOKE_OTEL_LOG_METRICS` | `1` turns on the EMF sink; deploy writes it when `observability.emit_log_metrics` is declared |
| `YOKE_OTEL_DISABLED` | Skip OTel entirely |
| `YOKE_OTEL_CONSOLE_EXPORT` | Local console traces/metrics |
| `YOKE_OTEL_SERVICE_NAME` / `YOKE_SERVICE_NAME` | Resource service name |
| `YOKE_API_LOG_LEVEL` | Process log level (`INFO` default) |
| `YOKE_API_DEBUG_SCOPE` | `function:` / `session:` / `request:` / `service:` campaign |
| `YOKE_API_DEBUG_UNTIL` | Required ISO-8601 end; past or missing disables capture |
| `YOKE_API_DEBUG_MAX_RECORDS` | Capture cap (default 200, hard cap 2000) |

## Shipping overview component timing

Authorized overview reads emit two bounded `Deployment start timing: ` records
with step `shipping_overview` through the existing timing emitter to stderr.
The end record carries the function request id and current trace id when present,
actual displayed run/member counts, `component_ms` and `component_calls`.
An absent function request id stays absent; use the trace id to join HTTP logs.
Components are `db_execute`, `db_fetch`, `qa_obligations`, `qa_acceptance`,
`repository_open`, `repository_resolve` and `ancestry_compare`; an unused
component is absent. These wall times overlap: QA composition includes its DB
and repository work. Do not add overlapping component totals or equate these
server measurements with browser selection-to-card or HTTP elapsed time.
Records contain no SQL, parameters, credentials, row values or full responses.
Non-overview reads do not enable this measurement. Run-card presentation reads
recorded exact-target QA without repository-provider ancestry requests. It still
reads current attachments, withdrawals, executable content and target identities.
Execution and settlement targets resolve once per run, stage and member in one
presentation; a new request re-reads receipts, and acceptance writes leave the
presentation snapshot before checking authority.
Admission, materialization and release gates continue to require source ancestry;
a card read never authorizes execution or settles a gate. Candidate resolution
reuse remains scoped to one evaluation on those validating paths.

Use the existing registered log read above with the request or trace id, then
inspect `shipping_overview` records alongside `HttpRequestCompleted` and the
handler event. Missing records are unknown, never a performance pass. Hosted
EMF totals alone cannot allocate component cost; the tenant role cannot read
the private database statement-statistics view.

For the production observation gate, run
`python3 -m runtime.api.tools.check_overview_latency --run-id RUN` from the
merged candidate checkout. It reads the run's latest ready Production receipt
and the following 24 hours of overview timings through registered CLI reads.
Wait until that window ends plus five minutes for log arrival. Missing or
unpaired timing records refuse; empty overviews cannot dilute the populated
overview p95. Passing requires populated p95 below five seconds and no failed
overview, including read deadlines. This is controller log evidence and needs
the hosting project's AWS log-read access.

## Steering report composition timing

For `steering.report.get`, read the `context.handler` fields on
`YokeFunctionCalled`. Use composed replies with `steering_report_build=headline`
and `steering_report_deliver=true` for watcher comparisons. Match seat scope and
compare the same report shape during and outside recorded Production releases.
Skipped and questions-only replies lack composition timings.

The `steering_report_compose_` prefix groups composition CPU, measured SQL
execution and an estimated non-SQL wait (wall time minus thread CPU and SQL
wall time, floored at zero). SQL wall time can include thread CPU, so the
remainder is approximate. Each observed dependency adds a `_calls` count and
`_ms` elapsed total. GitHub GraphQL and REST counts describe transport attempts,
including failures and retries. Token requests and retry waits are separate.
Landing reads, deployment progress, source lookup and lineage
containment are inclusive measurements. Their elapsed totals can overlap SQL
and GitHub time, and should never be added together. Dependency fields contain
no request arguments, repository names or report data. Once
`steering_report_compose_cpu_ms` is present, an omitted dependency had no
observed calls in that composition. Its absence on older records means unknown.

## Running more than one API worker

`YOKE_API_WORKERS` (default 1) sets how many uvicorn worker processes serve
the API. The parent process does boot work once: the startup lock, schema
convergence and permission seeding. Then each worker imports the app and runs
its own lifespan. Every side effect a worker could repeat is guarded in
Postgres (claimed rows, row locks, advisory locks, unique indexes), and no
request waits on an in-process wakeup. The relay long-poll polls the database.
Only one worker runs each control-plane upkeep pass at a time
(`UPKEEP_LOCK_KEY` session advisory lock). Each process exports metrics under
its own `service.instance.id`, so sum per-process series such as
`yoke.api.process.cpu.percent`.

These remain per process:
- Read caches: the steering schedule (15s), carried work (30s), OIDC
  discovery and similar. A client whose requests alternate between workers
  can briefly see an older answer after a newer one.
- The health snapshot and the GitHub App attestation. Each worker attests
  once at startup, so after one worker's failed attestation, `/v1/health` can
  differ by worker until that worker restarts.
- The debug-capture record cap, which applies to each worker separately.
- The connection reuse pool and threadpool, so peak Postgres connections
  scale with the worker count. Size `max_connections` for it.

Each worker adds about 100 MB of resident memory at import, before its working
set.
