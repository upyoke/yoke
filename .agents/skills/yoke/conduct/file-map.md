# Conduct — supplemental owners

The router owns the sole phase table. Use offset/limit reads of a named heading
when a phase needs depth; never load every supplement into a dispatch.

## Successor owner map

| Responsibility | Read |
|---|---|
| Entry sync, candidate filters, activation | [entry-activation.md](entry-activation.md), [entry-activation-resolution.md](entry-activation-resolution.md) |
| Fan-out routing and per-task closeout | [engineer-tester-loop.md](engineer-tester-loop.md) |
| Context section index | [dispatch-context.md](dispatch-context.md) |
| Submission remediation | [dispatch-context-gates.md](dispatch-context-gates.md) |
| Reflection capture and review artifacts | [dispatch-context-artifacts.md](dispatch-context-artifacts.md) |
| Parallel Engineer/Tester | [dispatch-context-dispatch.md](dispatch-context-dispatch.md), [dispatch-context-prompts.md](dispatch-context-prompts.md) |
| Integration gate | [simulation-gate.md](simulation-gate.md) |
| Auto-fix delegation | [simulation-autofix.md](simulation-autofix.md) |
| Exit custody and cleanup | [cleanup-report.md](cleanup-report.md) |
| Named halt/retry | [error-handling.md](error-handling.md), [retry-budgets.md](retry-budgets.md) |

Known-large specs/diffs remain file-backed and size-gated at their dispatch
owner. Supply exact paths and read instructions rather than abbreviated diffs.
