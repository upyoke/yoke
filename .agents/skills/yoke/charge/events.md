# /yoke charge — events emitted

## Events

This skill emits these structured events via the internal telemetry emit surface registered in `event_registry`:

- **FrontierComputed** — Emitted by the core Python frontier path (`yoke_core.domain.frontier_compute`) on every `compute_frontier()` call. No longer emitted by the charge skill directly.
- **ChargeDecisionMade** — Emitted on every terminal charge exit: after dispatch (step 6), on no runnable items (step 2), on `--dry-run` (step 3), when an explicit target is unavailable (step 4), on operator cancellation (step 5), and if an unexpected `wait` next_step is encountered during dispatch (step 6). Captures the selected item (if any), `next_step` (dispatch truth), `adapter` (raw frontier category), dispatch status, no-dispatch reason, and project.
