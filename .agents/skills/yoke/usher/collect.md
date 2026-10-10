# Usher — collect and validate

Use only the operator's explicit complete public refs; no discovery mode.
No refs means usage and stop. Resume selects one ref and deploy-only.
Retain dry-run/merge-only/deploy-only flags. Never reconstruct refs from IDs.

Read each item's live pin, exact definition, merge receipt and project:

```text
yoke workflows item get PREFIX-N --json
yoke workflows version get {workflow_id} {workflow_version} --json
yoke items get PREFIX-N merged_at project deploy_stage --json
```

The half-open binding must select Usher. Derive admission stages from that
definition. Standard mode admits its unlanded merge-ready stage, or a landed
pre-release review stage for idempotent close-out. For example,
reviewing-implementation with merged_at must reuse yoke merge item, not land
again. Deploy-only/resume admits declared delivery wait or already-landed
review/merge-ready stage; deploy-only additionally verifies delivery posture.
Done skips. Other stages reject with pin, live stage and receipt read named;
never force a jump or guess multiple-merge semantics.

## Integration gate and order

Read the producer's scoped result once per admitted item:

```text
yoke items dependency list PREFIX-N --json
```

Require result.integration_gate.evaluated and consume is_blocked/blockers.
Absent/malformed gate is dependency_integration_gate_unavailable: stop and
install the declared producer floor; no local checker or absence fallback.
Any blocked item stops before computing merge order. Report each blocker,
gate_point, satisfaction condition/environment and persisted rationale.
coordination_only and activation-only edges are not integration blockers;
the producer evaluates integration and closure obligations, including exact
deployment facts. Inspect the same dependency reader for the full graph.

Topologically order the returned relevant directional rows: blockers first,
dependents after; a cycle or failed reader halts. Explain every defer/reorder
with stored rationale. Compare adjacent lane edits against their project's
declared default branch and warn on shared-file rebase needs.

## Advisory default-branch CI

Resolve project from the item, github_repo from projects.github_binding.status,
workflow_file from ci_workflow_file capability settings, and default_branch
from projects.get. Missing configuration skips this advisory; the configured
health check owns its nudge. When all exist:

```text
yoke github-actions check-ci REPO WORKFLOW --branch DEFAULT_BRANCH --project PROJECT
```

The registered action uses the verified App binding. Failed warns; passed,
running (including queued) and no_runs skip. This advisory never replaces
item QA or the merge gate.

## Dirty target and work claims

Before claim/merge/release writes, resolve each target project's registered
checkout and run its shared dirty classifier. Machine mapping owns paths;
projects have no repo_path field. Preserve managed-bookkeeping semantics:

```text
yoke dev run -- python3 -m yoke_core.domain.classify_dirty_files classify-dirty --project PROJECT --exclude-worktrees
```

Read its actual result per help/source; unresolved project, failed classifier
or user-authored dirty files hard-stop. Commit/stash only authorized state;
never treat an unreadable result as clean.

Dry-run keeps these reads but skips claim acquisition and reconciliation
writes. For execution, acquire every admitted item claim before plan or recovery:

```text
yoke claims work acquire --item PREFIX-N --reason usher_collect --json
```

Any claim_conflict stops the batch with named holders: wait/coordinate or
operator claim recovery. Do not merge a subset because not all claims arrived.

If deploy_stage reports a failed stage, verify actual GitHub conclusion under
the claim before retrying. If externally succeeded, reconcile first:

```text
yoke usher reconcile-github PREFIX-N
```

Then follow its resume command. Actual failure needs run-log diagnosis;
still-running waits for terminal evidence. Continue to [plan](plan.md).
