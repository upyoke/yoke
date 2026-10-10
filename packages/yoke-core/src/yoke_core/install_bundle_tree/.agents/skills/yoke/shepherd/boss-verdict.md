# Shepherd — Boss review

After worker (or directly later edges), dispatch Boss with metadata only;
Boss reads authority itself. Every edge scope=plan; final reviews all artifacts.
No inline stale/summarized artifact replaces DB reads.

Before dispatch, source-verified records use **public_ref**, the supplied
_item_ref; never a fixed prefix/internal-ID storage key.
Count [UNPARSEABLE_BOSS_OUTPUT] for this ref/edge; at two genuine failures request
the configured stronger harness model. Record unavailable model as an explicit
shepherd_boss_model_unavailable deferral/recovery, never pass another provider's
model alias. Existing Claude choices are opus escalation/haiku extraction;
other harnesses must resolve supported configured models before dispatch.

Capture current maximum verdict ID for exact ref/edge/worker; parser recovery
may use only newer rows from this invocation:

```text
yoke db read "SELECT COALESCE(MAX(id),0) FROM shepherd_verdicts WHERE public_ref='ITEM' AND transition='EDGE' AND worker='WORKER'"
```

Render DispatchDescriptor(role="boss", optional supported model extras) through
render_for_harness for the verified harness. Prompt owns:
original ref/title/workflow/root, edge/worker, scope plan; authoritative
technical_plan/worktree_plan/spec/design_spec reads, body only when field empty;
current simulation, caveats and retry feedback. First edge DoD
Project/Flow/Rationale/recognized flow check is advisory CAVEATS, not NOT_READY;
final edge checks event coverage for new user workflows/state/system operations.

Mandatory review: requirements/ACs/caveats/narrative self-consistent; mutations
cover failure/recovery/leaves-behind state; replacement/rename/removal covers old
path deletion; broad changes use discovery searches rather than memory lists;
unresolved interface/files/data/operator behavior questions are NOT_READY;
Technical Plan approach/edge cases/tests explicitly evaluated.
Return structured VERDICT and full reasoning **as text only**, no DB persistence.
Treat rejection as systemic spec/dispatch/input gaps, record root cause in
reflection, no agent blame.

Next [parsing/triage](boss-verdict-rubric.md), then
[result routing](boss-verdict-transitions.md).
