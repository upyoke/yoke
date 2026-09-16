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
control-plane events:

- Every HTTP request logs `request_id` on `HttpRequestCompleted`.
- Function dispatch records `request_id` on `YokeFunctionCalled` events
  and on the OTel span (when a trace sink exists).
- Unexpected handler failures emit one bounded
  `FunctionCallHandlerFailed` log (`function_failure_observability`).

Collect a window, then stop. Do not leave a process-wide debug mode on.

Hosted logs (operator AWS credentials, not the test Mac):

```bash
aws logs filter-log-events --log-group-name /yoke/<env>/core \
  --start-time <epoch-ms> --end-time <epoch-ms> \
  --filter-pattern '"<request-id-or-session-id>"'
```

Control-plane events, any install:

```bash
yoke events query --session <session-id> --since '<start>' --until '<end>' --limit 100
yoke events query --item PREFIX-N --since '<start>' --limit 100
```

`--since`/`--until` and CloudWatch `--start-time`/`--end-time` are the
duration bound. `--limit` and the failure logger's 160-character value
cap bound output. There is no in-process auto-expiring DEBUG overlay;
raise `YOKE_API_LOG_LEVEL=DEBUG` or `YOKE_OTEL_CONSOLE_EXPORT=1` only
for a local/self-host session you will restart to clear.

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
