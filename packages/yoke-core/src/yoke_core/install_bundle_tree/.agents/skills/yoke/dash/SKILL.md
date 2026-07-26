---
name: dash
description: "File or execute instruction-sized Dash work through survey, isolation, verification, merge, and evidence."
argument-hint: "\"instruction\" | {PREFIX-N}"
---

# /yoke dash

Execute one instruction-sized work item end to end. A new instruction is
filed and executed immediately; an item reference resumes an existing Dash.
Dash uses ordinary item, claim, worktree, lifecycle, QA, merge, and
deployment surfaces. It does not route through `/yoke idea`.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Inputs

- `/yoke dash "instruction"` — author a concise title, file the Dash, and
  execute it in this session.
- `/yoke dash PREFIX-N` — execute the already-filed Dash.

`yoke dash "title" "instruction"` is the non-harness filing adapter. It
files and prints the item; it does not execute it.

## Invariants

- Treat the stored instruction as the complete requested scope.
- Perform all writes in the registered item worktree, never in main.
- Registered work and path claims always win over claim-less Dash work.
- Do not create child items. If the instruction has grown into planning or
  multi-slice work, use the escalation operation, which records the
  findings, files one Issue through normal intake, links it, and cancels
  the Dash.
- Honor every enabled item-posture knob. Posture can tighten execution; it
  cannot remove a workflow gate or a governed migration invariant.
- Do not transition to `done` until the branch is merged and the evidence
  record contains the result, passing verification, merge identity,
  touched files, and every enabled posture check.

## Execute

### 1. Resolve or file

If the argument is not an item reference:

1. Write a specific title of at most 100 characters.
2. File with:

   ```text
   yoke dash "<title>" "<instruction>" --json
   ```

3. Keep the returned item reference as `ITEM`.

If the argument is a reference, use it as `ITEM`. Read the workflow-aware
projection:

```text
yoke items detail get ITEM --json
```

Require `workflow_id=dash`, status `idea` or a resumable Dash stage, and
retain the stored instruction and `item_posture`.

### 2. Infer and survey the touch set

Read the repository just far enough to name the files or directories the
instruction is likely to touch. Prefer file paths; use a directory only
when the instruction genuinely spans that directory.

Record the survey:

```text
yoke direct-workflow dash survey ITEM --path <path> [--path <path> ...] --json
```

For every reported contact:

- yield to active or planned registered claims;
- coordinate with the owning item or wait when the scope is still small;
- if the work needs durable reservation, enable the allowed path-claims
  posture and register the complete inferred set through
  `yoke claims path register`;
- if contact repeats or the required work is no longer instruction-sized,
  follow **Escalate** below.

Never remove a required file merely to make the survey clear.

### 3. Claim and isolate

Prepare the ordinary item lane:

```text
yoke direct-workflow worktree prepare ITEM --workflow dash
```

Use the returned absolute `worktree_path` for every read, edit, test, and
git command. The preparation call acquires the item work claim, activates
any selected path claims, and creates or reuses the registered worktree.

Activate through the shared lifecycle interpreter:

```text
yoke lifecycle transition ITEM --from idea --to implementing --reason "Dash execution started"
```

The transition must pass the live `conflict_survey` gate. A stale or
newly-blocked survey is a coordination stop, not a bypass candidate.

### 4. Execute the instruction

Make the smallest complete change. Preserve unrelated work. Apply the
repository's simplify doctrine and governed database rules. Run focused
checks while editing. Capture every non-trivial test or build before
inspecting its tail.

If the instruction is investigative, the durable result may be a
well-grounded no-change finding. Do not invent a code change merely to
produce a diff.

### 5. Verify and close review

Run the relevant project verification and an agent self-check. Then execute
each enabled posture knob from `item_posture`:

- `verification` — run the selected plan or ad-hoc method case and retain
  its passing evidence;
- `path_claims` — confirm actual touched paths remain covered;
- `approval_on_done` — let the shared transition create or resolve its
  decision request; never self-approve;
- `deployment` — run the selected/default project flow after merge.

Move into the verification-close stage only when implementation checks
pass:

```text
yoke lifecycle transition ITEM --from implementing --to reviewing-implementation --reason "Implementation complete; verification passed"
```

### 6. Re-survey actual files and merge

Resolve the exact touched set from the worktree diff. Re-run the survey
with every actual file immediately before merge:

```text
yoke direct-workflow dash survey ITEM --path <actual-file> [--path <actual-file> ...] --json
```

If the result is blocked, do not merge. Coordinate, wait, tighten with
claims, or escalate. When clear, commit the coherent change and merge the
registered branch through the project's normal protected merge path. Do
not force-push, bypass CI, or merge around a registered claim. Record both
the implementation commit SHA and resulting merge SHA.

For a verified no-change result, use the inspected base SHA for both
identities and set `--no-changes`; no empty commit is needed.

### 7. Record evidence and finish

For each enabled posture key, supply one
`--posture-check key=passed`. Record the close:

```text
yoke direct-workflow dash evidence ITEM \
  --result "<what changed or was learned>" \
  --verification "<checks and evidence>" \
  --commit-sha <sha> --merge-sha <sha> \
  --path <actual-file> [--path <actual-file> ...] \
  [--posture-check <key>=passed ...]
```

Use `--no-changes` instead of `--path` only for a genuine no-change result.
Then transition through the `dash_evidence` gate:

```text
yoke lifecycle transition ITEM --from reviewing-implementation --to done --reason "Merged and evidence recorded"
```

Run any selected after-merge deployment action before the final
transition. Finally release the item work claim:

```text
yoke claims work release --item ITEM --reason "Dash completed"
```

## Escalate

Escalate as soon as the required outcome needs crafted acceptance criteria,
substantial design, durable multi-file coordination, or multiple delivery
slices. Summarize what was discovered and the remaining work:

```text
yoke direct-workflow dash escalate ITEM \
  --issue-title "<specific title>" \
  --findings "<grounded findings and remaining outcome>"
```

The operation is idempotent: it preserves one link to the absorbing Issue
and cancels the Dash. Stop Dash execution after it succeeds and release the
work claim if the operation did not already do so.
