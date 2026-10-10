# Conduct — integration simulation gate

Enter only after every generated task is reviewed-implementation/done (or the
pin's declared equivalent terminal task status). Verify all chains, not only
the current branch. Simulation checks cross-task behavior before fresh delivery
handoff; local verdict is never stored proof.

Explicit --force/--ignore-gaps skips simulation with a visible exact warning and
NO simulation record. Go to cleanup for this bypass leg; it cannot fabricate
CLEAN or automatically satisfy a downstream blocking gate. Resolve the fresh
parent pin and its declared handoff, retaining every unfulfilled obligation.

Otherwise read [simulation-gate-criteria.md](simulation-gate-criteria.md):
default compressed two-phase, standard only configured override, exact epic/
worktree evidence, bounded retries, then registered simulation-upsert receipt.
Missing prerequisite fields fail closed; no removed helper fallback.

Then [simulation-gate-escalation.md](simulation-gate-escalation.md):
CLEAN native parent gates+verified handoff; GAPS with PROCEED/no criticals exact
follow-up/triage discharge; no-auto-fix HALT; other gaps shared Simulate auto-fix
and at most one code amend cycle. Failed persistence/attestation remains HALTED,
never ordinary gap repair or a local CLEAN claim.

Every exit uses [cleanup-report.md](cleanup-report.md).
