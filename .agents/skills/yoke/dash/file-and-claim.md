# Dash phase 1 — resolve or file, then claim

## If the argument is not an item reference

1. Resolve the target project as `PROJECT`; the workflow is `dash`.
2. Before authoring the title or changing the supplied instruction, read the
   registered `workflow.execution_instruction.resolve` projection and obey
   every matching instruction:

   ```text
   yoke workflow execution-instruction resolve --workflow dash --project PROJECT
   ```

3. Write a specific title within the project's effective title limit
   (`yoke workflows definition get --project PROJECT` serves it as
   `title_max_length`).
4. File with, passing `--execution-instructions-considered` to attest the
   read in step 2 (the create refuses without it, and no adapter sets it
   for you):

   ```text
   yoke dash "<title>" "<instruction>" --execution-instructions-considered --json
   ```

   When the instruction asks for a screenshot or other visual evidence, pass
   `--verification-method browser-inspection` on that same file command.

5. Keep the returned item reference as `ITEM`.

## If the argument is a reference

Use it as `ITEM`. A bare number resolves as the current project's public item
sequence. Do not invent or guess a prefix; pass the operator's token through
unchanged.

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

Next: [`survey-and-isolate.md`](survey-and-isolate.md).
