# Minimal Tester Output-Gate Retry

Used by `engineer-tester-closeout.md` after an empty or unparseable verdict.

Render the minimal retry variant of
[the shared Tester template](../shared/tester-dispatch-template.md).
On retry 1 use the default model; on retry 2 use the shared descriptor's model
escalation. Keep the exact task identity, QA roster, project commands, absolute
lane path, changed files, and durable review-insert requirement. Omit inline
diffs and provide their capture paths instead. The prompt target is under
2000 tokens excluding the spec.

Read watcher capture paths from the wrapper. After the Tester returns, continue
at the caller's verdict gate, which requires the persisted task review row.
