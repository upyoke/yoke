# Active — QA Seeding

Implement owns seed → implement → test → record in its single lane.
Project-default and item-attached plans are the primary source.
[Test and record](test-and-record.md) materializes immutable cases at the
pinned verification transition. Do not derive consolidated requirements
from item type, AC prose or Browser posture.

For every acceptance criterion, select an attached plan case that proves it.
A missing mapping refuses as `requirement_proof_required`: author the proving
case in the project's plan, attach it, and materialize at the pinned QA stage.
Never copy acceptance prose into a blocking methodless requirement.

```bash
yoke qa item-plan attach --item PREFIX-N --project PROJECT --plan-id PLAN_ID --transition QA_STAGE --qa-phase verification
yoke qa plan materialize --item PREFIX-N --transition QA_STAGE
```

For a one-off check, use `qa.requirement.add` with a registered `--method-id`,
complete instructions, expected outcome and method config; read its `--help`.
The session holds the item claim. Read the pinned workflow for its QA stage;
Dash premerge plans must first be selected in verification posture.

Only a genuinely uncategorized item with no attached plan and no AC gets an
explicit `implementation_review` requirement with success policy `all-pass`.
A default-testing workflow without a registered command instead structurally seeds
`no_tests_declared` where quick would run. Record that stored kind as
`performed_by=agent`: agent-attested/no-tests-declared proves review, not
an executed suite. `yoke qa no-tests attest --project P --reason "..."`
adds the operator's reason. The requirement is seeded structurally; command
absence cannot produce a vacuous empty gate. Replace the example's transition
with the actual pinned QA stage whenever it differs.

For an explicit Browser contract, follow [browser-seeding.md](browser-seeding.md):
reuse a plan or author a method case. Do not seed free-form quick/full/e2e/smoke
requirements or inspect structure command settings as a substitute for plan
defaults. The transition router materializes project-owned cases.
