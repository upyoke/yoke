# Active — QA Seeding

Implement owns seed → implement → test → record in its single lane.
Project-default and item-attached plans are the primary source.
[Test and record](test-and-record.md) materializes immutable cases at the
pinned verification transition. Do not derive consolidated requirements
from item type, AC prose or Browser posture.

For explicit coverage outside attached plans, use `qa.requirement.add`:

For a pin whose gated stage is `reviewed-implementation`, the example is:

```bash
yoke qa requirement add --item PREFIX-N --qa-kind ac_verification \
  --qa-phase verification \
  --workflow-transition reviewed-implementation \
  --blocking-mode blocking --requirement-source ac_derived \
  --success-policy "<observable passing outcome>"
```

The session already holds the claim. Read `--help` for methods, task selectors
and deployment-run attachments; the transition must be the QA-gated stage
selected by the immutable definition.

Only a genuinely uncategorized item with no attached plan and no AC gets an
explicit `implementation_review` requirement, with a success policy that the
implementation matches its title/description. A default-testing workflow
without a registered command instead structurally seeds
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
