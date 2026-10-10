## Root-Cause Analysis Protocol

Read before fixing any failed test or unexpected behavior. Diagnose, rather
than pattern-match error text into a speculative patch:

1. Read the assertion: exact expected and actual values.
2. Inspect context with `yoke events tail --limit 20` or
   `yoke events anomalies --since "2 hours ago"`. Timing/nonzero_exit/
   benign_failure may identify upstream symptoms; telemetry is disposable.
3. Trace actual source/data flow from assertion to creating/configuring owner,
   including function/table/schema. Never infer owner from the error text.
4. State the discrepancy: test expects X, implementation produces Y.
5. Record one-sentence root cause in progress notes before patching. Explain
   the missing system contract, context, validation or guardrail, never
   "agent error." If the cause cannot be stated, investigation is incomplete.
6. Change minimum necessary code, then verify root cause and regression.

Error-message resemblance alone is not a root cause; repeated speculative
fixes are evidence to trace the owning path.
