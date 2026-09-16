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

Disable the log sink with `YOKE_OTEL_LOG_METRICS=0`. Force it on
(including local/self-host) with `YOKE_OTEL_LOG_METRICS=1`. Hosted
`prod`/`stage` enable it by default.

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
`session_id` / `function`. After `UNTIL` or the record cap, capture
stops even if the process keeps running. Unmatched DEBUG is dropped.
INFO/ERROR logs and metrics are unchanged. Campaign env never becomes a
metric attribute.

Producers that want extra payload (for example a full function result on
`YokeFunctionCalled`) call the same gate, default off:

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

`YOKE_API_LOG_LEVEL=DEBUG` without a campaign remains the local
restart-to-clear path. Do not leave it on in hosted processes.

Query windows still help read what was captured:

```bash
aws logs filter-log-events --log-group-name /yoke/<env>/core \
  --start-time <epoch-ms> --end-time <epoch-ms> \
  --filter-pattern '"<request-id-or-session-id>"'
yoke events query --session <session-id> --since '<start>' --until '<end>' --limit 100
```

OTLP traces: set `OTEL_EXPORTER_OTLP_ENDPOINT`. Hosted EMF mode does not
export spans.

## Related flags

| Flag | Effect |
| --- | --- |
| `YOKE_ENVIRONMENT` / `APP_ENV` | Resource environment; hosted `prod`/`stage` enable EMF |
| `YOKE_OTEL_LOG_METRICS` | `1`/`0` override for the EMF sink |
| `YOKE_OTEL_DISABLED` | Skip OTel entirely |
| `YOKE_OTEL_CONSOLE_EXPORT` | Local console traces/metrics |
| `YOKE_OTEL_SERVICE_NAME` / `YOKE_SERVICE_NAME` | Resource service name |
| `YOKE_API_LOG_LEVEL` | Process log level (`INFO` default) |
| `YOKE_API_DEBUG_SCOPE` | `function:` / `session:` / `request:` / `service:` campaign |
| `YOKE_API_DEBUG_UNTIL` | Required ISO-8601 end; past or missing disables capture |
| `YOKE_API_DEBUG_MAX_RECORDS` | Capture cap (default 200, hard cap 2000) |
