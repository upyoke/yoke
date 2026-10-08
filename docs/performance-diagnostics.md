# Performance implementation evidence

The public usage and measurement contract is in
[Performance diagnostics](public/reference/performance-diagnostics.md).
The page follows the approved prototype's Yoke Events chart only. No private
infrastructure, billing, cost or junkyard panels are included.

Existing measurement owners reused: `yoke_function_dispatch_events.emit_called`,
`observe_event_emission`, `hook_overhead_tool._classify_call`, repaired
`session_tool_calls` endpoints, and `HookDispatchTelemetry`. The current request
phase/DB/external OpenTelemetry spans have no event-ledger read owner, so
inspection states their absence instead of inventing spans or another pipeline.

The tests cover true observation p95, weighted averages, measured zero versus
null, retention gaps, bounded points, repaired/deduplicated tool timings across
Claude/Codex/Cursor, semantic wait classification, nested hook measurements,
ranked pagination and real project permissions. The query projects only required
timing context keys; it neither retrieves full function results nor preloads tool
responses. Oversized reads explicitly refuse without a partial aggregate.

## Hosted rollout ordering

Platform's existing `webapp/scripts/materialize_universe.py` copies the static
bundle and route contract together into `public/universe` and
`.generated/universe-contract` at build time. Its running old image therefore
keeps its existing navigation and route roster when only the engine updates.
The new engine does not mutate those materialized files. A direct Performance
path is safely unrecognized by the old roster, rather than throwing a contract
error or adding a navigation link that the old consumer cannot admit.

`test_performance_hosted_consumer.py` executes the actual committed Platform
`hosted-dashboard-paths.ts` source, snapshotted as a test fixture with its SHA256
and commit metadata, against both the previously consumed roster and this
candidate. Existing routes keep their behavior, an old roster safely refuses
Performance, and the same consumer with the new roster admits Performance.
Platform separately builds against the exact released candidate before adopting
the contract. Its consumer source identity is recorded beside the fixture;
these tests do not claim a private infrastructure deploy or consumer build.
