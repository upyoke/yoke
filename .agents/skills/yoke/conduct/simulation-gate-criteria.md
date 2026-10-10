# Conduct — simulation dispatch and verified receipt

Retain full public _epic_ref, actual project/main root, all task statuses and
registered task branches/worktree_path rows. Missing code authority reports
evidence missing instead of inspecting main as a substitute.

## Before every initial/retry dispatch

```bash
if [ -z "${_epic_ref:-}" ]; then
 echo "[CRITICAL] _epic_ref lost between dispatches — refusing retry. Halting simulator gate."
 exit 1
fi
```

This check halts before any simulator invocation, initial dispatch or retry.
Follow [cleanup-report.md](cleanup-report.md) with HALTED; no hallucinated identity.
Render DispatchDescriptor(role="simulator") through the harness owner. Every
standard, compressed and retry prompt starts with the two-line verdict block:
SIMULATION: CLEAN or SIMULATION: GAPS FOUND, then EPIC: PREFIX-{N} using the
actual retained ref. The EPIC: PREFIX-{N} attestation line is mandatory even
when the output otherwise looks structured. No task-number-as-item conversion.

## Mode and evidence

Read sim_force_standard_integration from existing settings. true selects full
standard task/spec/plan/review context; otherwise compressed two-phase. Task/
review/spec/plan/diff bytes and task count are logged for observability, not a
mode threshold. Exact code authority travels through every prompt:

> Worktree-State Authority: a task's resolved worktree checkout is the authority
> whether the item/epic has one worktree or many. Main is the base/integration
> target, not evidence of unmerged task state. Use each task's registered
> worktree_path/branch or supplied diff; otherwise report evidence missing.

Compressed bundle contains Interface Contracts Per Task, Shim Re-Export
Contracts, File Overlap Matrix, Dependency Edges, ## Worktree Authorities
(_worktree_list), Diff Stats Per Branch and Task Statuses. Dependencies are
actual epic_tasks.dependencies, never a fabricated depends_on column:

```text
yoke epic-tasks list --epic PREFIX-N --json
yoke workflow-item epic-dispatch-chain list --epic PREFIX-N --json
yoke db read --format lines "SELECT task_num, title, dependencies FROM epic_tasks WHERE epic_id=(SELECT item_id FROM item_refs WHERE public_ref='PREFIX-N') ORDER BY task_num"
```

For shims, the source import list is the source of truth: include every public
and underscore-prefixed re-export such as _BLOCKS, never infer from child
internals. Commit-Boundary Evidence supplies a bounded parent
`git log --oneline -- {file}` line for each discrete-commit/NFR-style AC or
separate-commit requirement.
If no file named, say
`commit evidence unavailable: no affected file named`. Parent evidence is
allowed; do not run git log or git blame yourself in Simulator.

Phase A uses ONLY prompt evidence, no tools: preliminary verdict and at most3
candidate gaps. Phase B optionally verifies via at most5 named file reads and
specific-file diffs. No broad branch diff, ls/find/glob enumeration, unnamed
files or git archaeology unless explicitly requested. Final report has severity,
category, path/trigger/consequence/root cause/fix and recommendation.

## Parse and bounded output retry

Immediately continue on return; capture reflections before discarding output.
Initialize _local_result=""; parse SIMULATION: CLEAN/GAPS FOUND, with a local
fallback token only for output diagnosis. Persistence still validates identity
and canonical headers; substring parsing cannot authorize handoff.

No result enters [retry-budgets.md](retry-budgets.md). At retry1 distinguish
formatting_omission from context_exhaustion; ambiguous is formatting_omission.
Formatting retry explicitly demands SIMULATION: then EPIC: ${_epic_ref} first.
Compressed aggressive retry repeats SIMULATION: then EPIC: ${_epic_ref}, bounded
phases, source shim/commit evidence and worktree authority. Retry2's no-tool
maximum3-gap prompt likewise repeats SIMULATION: then EPIC: ${_epic_ref}, retaining
required overlap/dependency/task/shim/commit evidence and actual lane identities.
Reread the identity check before each invocation. Capture/parse each return.
Exhaustion logs classification/tier and HALTs; never synthetic CLEAN.

## Persist once and require its receipt

Save complete report locally and request JSON on the ORIGINAL write:

```text
yoke workflow-item epic-task simulation-upsert --epic PREFIX-N --phase integration --stdin --json < {REPORT_FILE}
```

Require success=true, matching public_ref/phase/verdict, verified=true and
positive integer requirement_id/run_id. Use result.verdict as _verified_verdict
and downstream _local_result; no local override or empty-field fallback. Receipt
verifies that exact durable attempt, not automatic lifecycle/claim handoff.
Missing receipt fields is producer_unavailable: named control-plane deployment
repair, then readback. Never use a retired source helper or repeat write for a
different output format.

`simulation_identity_mismatch` diagnoses a wrong-epic body;
`simulation_identity_missing` diagnoses absent leading headers. Retain the
intended ref and report's attested ref; recover with the required leading
SIMULATION and EPIC headers for the exact intended item. Readback failure
retains any returned ids:

```text
yoke workflow-item epic-task simulation-get --epic PREFIX-N --phase integration --json
yoke qa run list --requirement-id {requirement_id}
```

Uncertain write/refusal HALTs with its real diagnostic; do not manufacture a
passing record, silently select a newer concurrent attempt, or downgrade identity
failure into a fixable gap. The original capture and ids remain evidence.
Next: [simulation-gate-escalation.md](simulation-gate-escalation.md).
