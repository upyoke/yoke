# Durable validation reports

Read before writing or recording a report or verdict. Keep all review evidence
and the exact persistence contract below.

## Durable report and verdict

Epic review uses exact dispatch **Epic DB identifiers**, complete epic ref and
task number. Never derive ids from title/slug. Prepare report in authorized
scratch using granted report tooling and invoke:

```bash
yoke workflow-item epic-task review-insert --epic {epic-ref} \
  --task-num {task-num} --verdict {pass|fail} --body-file /tmp/yoke-review.{task-num}.md
```

Function `workflow_item.epic_task.review_insert`; verdict case-insensitive.
body-file is preferred when an authorized report file exists. Use --stdin for
literal report content when scratch writing is outside the tool grant; never
invoke denied Write/Edit tools. No source edits.
Standalone uses existing seeded AC-verification requirement from
`yoke qa requirement list --item PREFIX-N`, then packet `yoke qa run add`:
records claimed HEAD/--head-sha verification_tree and --raw-result evidence.
Never invent new requirement; reviewed-implementation consumes seeded rows.

Report contains `**VERDICT: PASS**` or `**VERDICT: FAIL**`. Binary only, no
conditional pass. Blocker=FAIL; informational path warnings do not change verdict.

## Validation Report Template

In order: `# Validation Report: Task #{issue-number}`, `## Result: PASS | FAIL`,
`## Acceptance Criteria`, `## Tests`, `## Test Commands Used`, `## E2E Validation`,
`## Regression Analysis`, `## Interface Contracts`, `## Documentation`,
`## Code Quality`, `## Path Tracing`, `## Issues Found`, `## Recommendation`.
Record AC-by-AC PASS/FAIL, chosen/excluded test rationale, exact commands,
regression classification, contracts/docs, concrete failures and binary recommendation.
