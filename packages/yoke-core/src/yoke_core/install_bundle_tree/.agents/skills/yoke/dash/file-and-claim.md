# Dash phase 1 — resolve or file, then claim

## If the argument is not an item reference

1. Resolve the target project as `PROJECT`; the workflow is `dash`.
2. Before authoring the title or changing the supplied instruction, read the
   registered `workflow.execution_instruction.resolve` projection and obey
   every matching instruction:

   ```text
   yoke workflow execution-instruction resolve --workflow dash --project PROJECT --full
   ```

3. Write a specific title within the project's effective title limit
   (`yoke workflows definition get --project PROJECT` serves it as
   `title_max_length`).
4. File with, passing `--execution-instructions-considered` to attest the
   read in step 2 (the create refuses without it, and no adapter sets it
   for you):

   ```text
   yoke dash "<title>" --stdin --execution-instructions-considered --json <<'EOF'
   <instruction>
   EOF
   ```

   Positional `INSTRUCTION` is still accepted for text that needs no
   backticks or `$(`. Free text that names commands goes on `--stdin` or
   `--content-file` so the shell cannot substitute it.

   When the instruction asks for a screenshot or other visual evidence, pass
   the posture
   [Where a Browser case runs](../../../../.yoke/docs/reference/browser-scenarios.md#where-a-browser-case-runs)
   selects on that same file command:
   `--verification-method browser-inspection` for a served change,
   `--approval-on-done` for a change no server serves.

   When the item will ship in a release on a flow other than the project
   default — a shared release the operator named, say — pass
   `--deployment-flow FLOW` on that same command. The create validates it
   against the project's flows (`yoke deployment-flows list --project
   PROJECT`); choosing it here avoids a flow mismatch at composition.

5. Keep the returned item reference as `ITEM`.

## If the argument is a reference

Use the complete `PREFIX-N` ref as `ITEM`. A bare number is refused even with
project context. Do not invent or guess a prefix; request the full public ref
when the operator supplied only a number.

## Claim before anything else

**Claim the item first.** As soon as `ITEM` is known — whether just filed
or resumed — acquire the item work claim before any survey, budget, path, or
edit work. The claim is the
session's authority over the item and its worktree; hold it for the whole
Dash. This mirrors `/yoke idea` and `/yoke refine`, which claim before
touching any shared state:

```text
yoke claims work acquire --item ITEM --reason "Dash execution"
```

For a launched worker this is survival, not just order. A session holding no
claim is what the non-destructive session end reaps as idle, so a worker that
surveys before it claims can be ended mid-mandate: one spent 79 tool calls
reading the codebase, was auto-ended claim-free, and left its item looking
untouched. Claim before the first read, and that reaping becomes structurally
impossible.

If the instruction requested a screenshot, deployed evidence, or an approval,
follow [`../idea/delivery-requirements.md`](../idea/delivery-requirements.md)
before surveying.

## Read the item and its effective policy

```text
yoke items detail get ITEM --json
yoke workflows item get ITEM --json
```

The detail read serves the item's stored narrative and the operator execution
instructions that travel with it. It does not serve the rendered body or the
Progress Log: `result.item.content_index` names those with the exact command
that returns each, so read one when you need it rather than carrying both
copies of the same prose. `--full` serves every section.

Require `workflow_id=dash`, status `idea` or a resumable Dash stage, and
retain the stored instruction. Set `FILE_BUDGET_POLICY` and
`PATH_CLAIMS_POLICY` from `result.effective_policies.file_budget` and
`result.effective_policies.path_claims` in `workflows.item.get`. `required` is
on at item scope, `required_per_task` is on at generated-task scope, and
`optional` is off. The runtime projection owns historical compatibility and
allowed posture tightening. The 350-line authored-file limit remains on in all
combinations.

## Resuming an item already in flight

A Dash past `idea` was started by an earlier session — usually one steering
terminated to restaff the item onto a different model. Termination released
that session's claim and left the registered lane, its branch, and any
uncommitted work in place. Before acting, read where it stopped:

```text
yoke items section get ITEM --section 'Progress Log'
git -C <worktree_path> status --short
git -C <worktree_path> log --oneline <default-branch>..HEAD
```

The last checkpoint names the live stage, what is committed, and the next
step; the lane is the truth where they differ. Keep the uncommitted work.
Still record the survey and run preparation below — preparation reuses the
registered lane — but skip the `idea → implementing` transition when the item
is already past `idea`, then re-enter at the phase the live stage names in the
phase map in [`SKILL.md`](SKILL.md).

## Checkpoint before any stop

Before any stop short of `done` — a park, an escalation, a landing or release
wait, the end of a turn — append a Progress Log checkpoint naming the live
stage, what is committed, what is still uncommitted, and the next step, so a
restaffed successor can resume from it:

```text
yoke items progress-log append ITEM --headline "<checkpoint>" --stdin
```

Next: [`survey-and-isolate.md`](survey-and-isolate.md).
