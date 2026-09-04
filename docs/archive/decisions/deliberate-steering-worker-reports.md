# Steering workers report deliberately

Decision recorded 2026-09-04.

## Decision

Workers reach a steering seat only through a deliberate `yoke say --steering`
send. Ending a turn sends no Fleet message. The worker mandate names the
deliberate terminal report, and substantive-only guidance keeps progress in
the worker's own visible output.

The Stop-hook report router, its substance classifier, and its skipped-report
event were removed. They formed a second delivery channel whose inferred
intent could neither match a worker's deliberate choice nor avoid duplicate
mail reliably.

## Measurement

On 2026-09-04, the steering seat received 112 deliberate envelopes carrying
39 `DONE`, `BLOCKER`, or `HUMAN_GATE` reports. The automatic Stop route added
14 envelopes: two duplicated a deliberate send and the other 12 were noise.
Each noise envelope created an inbox row that required a hand acknowledgement.

One false positive was a watcher line shaped like
`# watch_merge digest ... failed ... BLOCKED ...`. Those words passed the
substance floor even though the line was progress output, not a worker's
decision to report a failure or blocker.

## Consequences

- Launch origin no longer changes how a worker reports.
- Terminal and other actionable reports use `yoke say --steering`.
- Wait notes, watcher digests, and other progress remain visible only in the
  worker's own session unless the worker deliberately sends them.
- Fleet message delivery, receipts, deduplication, and inbox rendering are
  unchanged.
