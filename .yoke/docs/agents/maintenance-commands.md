# Maintenance commands and context

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Agents](index.md) > Maintenance commands
<!-- /yoke:breadcrumbs -->

Use these operator and internal commands to maintain Yoke, inspect project context and follow the shared operation patterns.

## Operator maintenance and steering

### charge

Read the evaluated runnable frontier, show ranked reasons and adapter
classification, apply its operator selection gate and dispatch the bound skill.
Use the explicit project/scope and WIP policy; no guessed project. Read
[frontier details](../reference/charge-frontier.md) before selection.

### feed

Reconcile strategy and frontier facts: leave premature work in strategy,
refresh dependencies, sharpen/split existing work, or materialize stable new
items. Generated edges retain rationale and structured evidence. Feed owns
semantic graph maintenance; ranking, WIP and claims belong to their existing
owners. `--no-new-items` permits analysis/graph refresh without creation.

### strategize

Review the SML against current reality with source-backed research. Follow its
operator checkpoints for refresh, framing, research, proposed strategy changes,
frontier implications and actual tradeoff conflicts. DB strategy rows are
authority; rendered `.yoke/strategy/` files are views. Preserve decision and
checkpoint history. See [strategy](../strategy.md).

### onboard

Adopt a wired project's existing work: scan open issues, pull requests and
local session transcripts, settle strategy and CURRENT-PLAN one decision at a
time, configure only what the first work needs, then hand off to `/yoke steer`.
Done when the first item is done. Follow its approvals before infrastructure effects. Existing
credentials and host exclusions retain their custody and named refusals.
Machine `yoke setup` and harness onboarding are separate operations.

### doctor

Run applicable health checks with the watcher:

```text
yoke watch doctor -- --full
```

Keep the returned stream through exit. Each check declares project/tree/runtime/
capability scope; N/A names its reason and is neither pass nor omission.
Project-local `.yoke/doctor/` checks join the same report; import failure fails.
`--fix` follows the Doctor skill's repair gates, not blanket change authority.

### resync

Detect linkage, field and body drift between Yoke and GitHub; default is read-only.
Use `--fix` only within its authorized repair scope and verify retained linkage.

### curate

Cluster unreviewed Ouroboros observations, verify code and duplicates, route
actionable work to Dash or a scoped work item and archive handled entries.
Keep actual evidence and reasons; a field-note is not a discovered-work bypass.

### wrapup

Record current unfinished work, holds, blockers, next actions and durable links
in Progress Log; capture learning through Ouroboros. Do not replace active work
with an accumulated essay or a terminal status unsupported by delivery.

### help

Show this command reference and quick-start guidance. `/yoke` without arguments
selects help.

### freeze / thaw

Use `yoke items freeze` / `yoke items thaw` with their `--help`: frozen is an
orthogonal flag, not lifecycle status.

### block / unblock

Use `yoke items block` / `yoke items unblock` with their `--help` for an item's
own reason. Dependency edges own waits on another item; path-claim blocked
state is separate. Forward and closure gates still enforce their obligations.

## Internal Sub-skills

<!-- BEGIN GENERATED: skill-registry-internal -->
Internal skills are generated from `yoke_contracts.skill_registry`.

| Skill body | Purpose |
|---|---|
| `.agents/skills/yoke/amend/SKILL.md` | amend a synced task graph |
| `.agents/skills/yoke/approve/SKILL.md` | record a deployment approval |
| `.agents/skills/yoke/implement/implementing/SKILL.md` | kick off implementation |
<!-- END GENERATED: skill-registry-internal -->

These bodies serve the parent procedure; their existence does not bypass its
claim, binding or approval boundary. The Simulate and Usher phase maps include
support files that are not independent skill bodies.

## Internal Support Artifacts

`shared/tester-dispatch-template.md` is the sole Tester input contract for item,
generated-task, retry and simulation fixes: identity/spec, complete QA roster,
commands, lane, changed files, size-gated diff, ephemeral URL and durable receipt.

## Project Context Loading

Implement loads project context before text audit/discovery. Conduct adds the
project context and test/ephemeral facts to each role dispatch. Use declared
context routing and topic matches; report missing files and only then broaden
exploration. Checkout resolution uses one machine-local entry per project, independent
of the selected connection. One item targets one project; installed behavior stays project-owned.

## Key Patterns

- Registered function ids and their CLI adapters own state; raw SELECTs are
  diagnostic reads. Operator source-dev break-glass is separate authority.
- Complete structured fields and persisted reviews are authoritative; rendered
  bodies, boards and local strategy files are views.
- Required facts live in durable owners. Events are diagnostic and absence
  proves nothing; a quoted event name is not execution proof.
- [Project install](../projects.md) owns clean/current upstream, generated
  paths, commit/publication, protected-branch PR and named partial-state repair.
  Source-maintainer link/admin setup uses `yoke dev setup`, a distinct
  contributor operation rather than an external-project installation recipe.
- [QA](../qa.md) owns immutable requirements, actual execution, review and
  waivers. A command passing elsewhere cannot replace its selected case.
- Bindings and selected delivery flow determine close-out. Do not use a copied
  progression, scalar terminal write or unsupported skip to claim completion.

## Related

- [Slash Commands Reference](commands.md)
