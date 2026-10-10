# Dash — resolve or file, then claim

## New instruction

Resolve the target project before title or scope; never silently substitute
the current checkout. Read matching operator instructions through
`workflow.execution_instruction.resolve`:

```text
yoke workflow execution-instruction resolve --workflow dash --project PROJECT --full
```

Obey every returned instruction. Read the project's effective title limit
from `yoke workflows definition get --project PROJECT`.
Keep supplied instruction content intact and file through `items.create`:

```text
yoke dash "<specific title>" --project PROJECT --content-file /tmp/dash-instruction.txt --execution-instructions-considered --json
```

Author that file first; stdin is also valid. Commands/backticks/$() belong in
file/stdin, never shell-interpolated positional prose. The attestation is
required and no adapter supplies it for you. Read `yoke dash --help`.

For requested screenshot/deployed evidence, apply the posture selected by
[Browser placement](../../../../.yoke/docs/reference/browser-scenarios.md#where-a-browser-case-runs):
browser-inspection for a served change, approval-on-done where no server
serves it. Put the posture on this same create.
An operator-selected nondefault/shared release flow uses
`--deployment-flow FLOW` on create after validating the project's registered
flows; do not discover a composition mismatch after landing.

## Existing reference and first claim

Keep the full returned or supplied ref as ITEM. Never invent or guess a prefix;
a bare number requires the full public ref.

**Claim the item first.** Before survey, policy, budget, paths or edits:

```text
yoke claims work acquire --item ITEM --reason "Dash execution"
```

Hold it through the entire leg. Requested delivery/approval evidence also
uses [intake obligations](../idea/delivery-requirements.md) before surveying.

Read detail and effective policy:

```text
yoke items detail get ITEM --include '' --json
yoke workflows item get ITEM --json
```

Require the live Dash pin/stage; retain the stored instruction and operator
block. Detail's content_index names exact reads for body/Progress Log rather
than carrying duplicate narrative; use --full only for needed full sections.
Read workflows.item.get result.effective_policies. Required is item-scoped, required_per_task generated-task-scoped,
optional off. Central compatibility/posture projection owns the answer;
File Budget and path claims remain independent, 350 always on.

## Resuming an item already in flight

```text
yoke items section get ITEM --section 'Progress Log'
git -C {WORKTREE_PATH} status --short
git -C {WORKTREE_PATH} log -5 --oneline
```

Keep the uncommitted work; actual lane state wins over a stale checkpoint.
Survey and prepare still run, reusing the lane. Skip the entry transition
already completed and resume at the phase selected by the live pin.

Before every stop short of done, append actual stage, committed head,
uncommitted work and next action through `items.progress_log.append`:

```text
yoke items progress-log append ITEM --headline "<checkpoint>" --stdin
```

Next: [survey-and-isolate.md](survey-and-isolate.md).
