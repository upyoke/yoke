# Usher — generated-task preflight

Require canonical integration simulation:

```text
yoke workflow-item epic-task simulation-get --epic PREFIX-N --phase integration --json
```

Failed/empty read stops: run /yoke simulate PREFIX-N, then reenter. Unresolved
reported integration failures are not successful proof. Only explicit authorized
skip-simulation overrides this check; don't infer a waiver from one lane/manual
confidence. Retain exact authorization in evidence.

Read parent technical-plan acceptance criteria (body is virtual rendered field,
never raw items.body SQL) and registered graph/lane paths:

```text
yoke items get PREFIX-N technical_plan --json
yoke epic-tasks list --epic PREFIX-N --json
yoke item-worktrees list PREFIX-N --json
yoke items get PREFIX-N worktree_plan
```

Count every criterion before checks. Check against actual registered lane files,
not main before landing. If parallel verification is explicitly authorized,
pass exact paths and file-access scope to each verifier; Usher itself is inline.
Print before each check "Verifying AC i/total: text..." and afterward PASS or
FAIL with reason; finish pass_count/total summary. Unverifiable/unmet criteria
abort for a fix (/yoke amend or authorized current work) or explicit operator
acknowledgement. No criteria warns clearly; continue per existing contract.

Every task must be in its pin's accepted completed/reviewed/polished/delivery/
terminal posture, not predispatch/in-progress/failed. Standard accepted states
include reviewed-implementation, polishing-implementation, implemented, release
and done; custom pin owns actual selection. Report unfinished task rows and stop.

Use worktree_plan's declared merge order; empty plan uses registered graph/lane
branches. Independent branches can order freely; suggested dependency sequence
stays. Missing/unresolved path is lane_resolution_unavailable with registered
reader recovery, not a synthesized pathname. Continue to [lane loop](merge-lanes.md).
