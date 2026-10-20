# Idea — Infer and Create

## 2. Infer

- Project: explicit or the checkout's; else ask. See
  [reference-and-scope-verification.md](reference-and-scope-verification.md).
- Flow: [infer-deployment-flow.md](infer-deployment-flow.md).
- Workflow: smallest fitting active row of
  `yoke workflows definition get --project "$_project" --json`; epic only
  for parallel tasks. Dash: follow [Dash](../dash/SKILL.md).
  Blitz: refinement links one execution strategy doc; never start it here.
- Priority: never ask; urgent → high, cosmetic → low, else medium.

### c2. Resolve execution instructions before final authoring

Apply `workflow.execution_instruction.resolve` before writing (the receipt
copy remains defense in depth).

```text
yoke workflow execution-instruction resolve --workflow "$_workflow" --project "$_project" --full
```

## 5. Create The Item With Its Spec

Check `yoke items search` for duplicates first; a likely duplicate needs one
create-anyway yes/no.

```text
yoke items create --title "<title>" --workflow "$_workflow" --spec-file "$_spec_file" --entry-surface harness_skill --execution-instructions-considered --project "$_project" --priority <priority> --json
yoke claims work acquire --item "$ITEM_REF" --reason draft-in-progress
```

Persist requested waits with an explicit gate (`status:done`, `fact:merged`
or `fact:deployed:ENV`):

```text
yoke items dependency add "$ITEM_REF" <blocker-ref> idea --gate-point activation --satisfaction status:done --rationale "<requested wait>"
```

Screenshots or approval asked: [delivery-requirements.md](delivery-requirements.md).

## 7. Confirm

After release, show the ref, issue link and dependencies; route via
[shared handoff](../shared/stage-handoff.md).
