## Root-Cause Analysis Protocol

Read before fixing a failed test or unexpected behavior.

1. Read the assertion's exact expected and actual values.
2. Trace the real code and data path from the assertion to the owner that
   produces the value. Never infer the owner from error text.
3. State the discrepancy: the test expects X, the code produces Y.
4. Write the one-sentence root cause in the progress note before patching. If
   you cannot state it, keep investigating.
5. Make the smallest change that fixes the cause, then verify the cause and the
   regression.

`yoke events tail --limit 20` and `yoke events anomalies --since "2 hours ago"`
can point upstream, but events are telemetry and prove nothing by absence.
