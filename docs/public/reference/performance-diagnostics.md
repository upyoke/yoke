# Performance diagnostics

Open **Diagnostics → Performance**. Yoke Events uses the workbench's selected
universe and its existing All/multiple-project selection. It never combines
universes. Changing scope cancels previous reads and closes inspection.

The default window is the last 24 hours, ending now. Choose a preset or edit
From/To in local time; custom ranges use timezone-qualified UTC timestamps on
the wire. Refresh advances preset windows. Invalid or reversed dates name the
correction before querying. Hover a bucket for values, sample counts, and
resolution; click it or use arrow keys and Enter to inspect contributing calls.
Inspection ranks every matching observation by raw duration, with paginated
results and filters for functions, tools, hooks, relay waits, and watchers.

Ordinary function/tool latency and hook evaluator time use the left axis.
Relay long-poll and watcher wall time use the explicitly labeled right axis.
The dashed 2-second diagnostic target applies only to ordinary latency.
Each series can be toggled independently. Isolated observations remain points;
gaps stay gaps. Client hook wall time contains evaluator time: inspection shows
both and the measured remainder, without adding overlapping durations.

## Measurement and unknowns

Buckets use individual observations, sum/count means and the existing linear
interpolation percentile implementation. A bucket p95 is never an average of
p95s or a relabeled maximum. Source observations are event-resolution; buckets
are at least a minute and sized to the requested chart budget (20–800 points).
There is no invented finer-resolution data or interpolation across gaps.

`YokeFunctionCalled.duration_ms` measures the handler, not end-to-end request
wall time. `HarnessToolCallCompleted`, failed/structured/interrupted completion
variants use repaired `session_tool_calls` endpoints when present, preserving
timed, pending, unsupported and unknown distinctions across supported harnesses.
Duplicate tool completion events share one `(session_id, tool_use_id)` count.
`HookDispatchTelemetry.duration_ms` measures the evaluator; `client_wall_ms`
is separately inspected. The semantic operation `session_control.relay.claim`
identifies a relay long-poll. A stored command summary naming a registered
`yoke watch` invocation identifies watcher wall time. A slow bare shell is
still ordinary tool timing; duration alone never classifies a wait.

Inspection exposes existing owner/event measurements, permitted command
summaries, harness/surface/machine, outcome, correlation identities and delivery
lag when both completion and observation timestamps exist. Request queue/auth,
DB and external dependency spans exported through OpenTelemetry are not stored
in this ledger and cannot be fabricated here. They are explicitly unknown.
No new collector, storage pipeline or private infrastructure access is required.

Counts cover delivered, retained observations, not events that never arrived.
Older history outside retention and unsupported/missing timings stay unknown.
The last observation timestamp is not a collector-health guarantee; query time
is labeled separately. Empty windows do not assert health or zero latency.

## Registered queries and bounds

`events.performance.aggregate` and `events.performance.detail` authorize every
selected project with `events.read` before reading or serializing observations
and summaries. All contains only accessible projects; universe-attributed rows
require an actual universe-admin grant and never enter selected-project metrics.
The serving connection owns universe identity; the payload accepts no universe,
actor, org or arbitrary query fields. There is no shared aggregate cache.

```text
yoke events performance aggregate --since 2026-10-08T00:00:00Z --until 2026-10-09T00:00:00Z --project-ids 1,2 --points 400
yoke events performance detail --since 2026-10-08T00:00:00Z --until 2026-10-08T00:05:00Z --family tool --limit 50
```

Read each command's `--help` for paging and bounds. Time, event-name and project
predicates use existing indexed columns. The aggregate reads only timing/context
keys and command summaries, never stored responses or ledger results. The range
is capped at 250,000 observations; larger ranges refuse by name and teach a
shorter range, rather than returning a silently sampled percentile. Detail
returns at most 100 contributors per page and labels the total and pagination.
Telemetry availability has no effect on operational correctness.

## Packaged chart dependency

uPlot 1.6.32 is pinned in the UI npm manifest and lockfile. Its minified runtime,
stylesheet and MIT license ship in the wheel's static assets; no runtime CDN is
used. To regenerate them, run `npm ci` under the UI directory and then:

```text
yoke dev run -- python3 -m yoke_core.ui.build_chart_dependency --target-root <checkout>
```

Use uPlot's [API documentation](https://github.com/leeoniya/uPlot/blob/master/docs/README.md)
and the pinned dependency's `dist/uPlot.d.ts` when changing chart interaction.
