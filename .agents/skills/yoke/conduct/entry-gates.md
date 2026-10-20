# Conduct — entry contract

No PREFIX-N: stop with `Missing required argument. Usage: /yoke conduct PREFIX-N`.
Flags: --max-attempts N (default 5), --no-chain (stop after this task),
--force/--ignore-gaps (skip simulation gaps with a warning), --no-auto-fix.

```text
yoke workflows item get PREFIX-N --json
yoke workflows version get WORKFLOW {version} --json
yoke items get PREFIX-N spec
yoke advance preflight hard-blocks PREFIX-N --gate-point activation
```

Use the skill_bindings row with from_stage_id ≤ live stage < through_stage_id;
else halt `conduct_binding_unavailable` or `conduct_skill_not_bound`. No
Acceptance Criteria: halt `acceptance_criteria_missing`. Hard-blocks nonzero:
halt with its BLOCKED rows.

Next: [entry-activation.md](entry-activation.md).
