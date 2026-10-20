# Simulate — dispatch prompts

Send yoke-simulator this contract plus the phase's inputs:

```text
Item: {public_ref}; phase: {phase}. Read-only.
Begin with SIMULATION: CLEAN or SIMULATION: GAPS FOUND, then EPIC: {public_ref}.
Tag gaps [CRITICAL], [WARNING] or [NOTE] with paths, fix guidance and
Fix level: plan|code|mixed. Uncertainty is GAPS FOUND.
```

Plan: spec, plans and task bodies. Integration: each task's worktree_path and
diff (main is only the base), excluded tasks, and Conduct's migration evidence.
Compressed integration sends diff stats and allows at most 3 candidate gaps
and at most 5 selective file reads.
