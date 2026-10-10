---
name: implementing
description: "Implementation kickoff inside /yoke implement: QA seeding, project context, test commands, and implementation guidance. Called after the item enters its implementation stage."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: ""
---

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

# Implementing Sub-skill

Entry/reentry has verified the pinned Implement binding, taken the claim and
recovered its single lane (or declared none policy). Generated-task workflows
belong to Conduct. Continue in the same session; no manual relaunch.

Every read/edit/test uses the exact registered WORKTREE_PATH. For a known
large file, load only relevant ranges. Test collection must use that lane;
`watch_pytest` refuses wrong cwd. [Implementation](implementation.md)
owns the Step 0 anchor and source-dev wrapper rules.

Apply AGENTS.md's Simplify doctrine during authoring. Before each slice and
every previously unnamed sibling edit, check coverage:

```bash
yoke claims path list --item PREFIX-N --state planned --state active --state blocked
```

Compare every required physical file with nonterminal coverage; widen missing
paths before edits. Budget and path claims remain independent axes.
Do not omit required scope to avoid a holder.

| Phase | Read/execute |
|---|---|
| QA seed | [qa-seeding.md](qa-seeding.md) |
| Browser seed | [browser-seeding.md](browser-seeding.md), only for explicit Browser contract |
| Project context | [project-context.md](project-context.md) |
| Tests/QA evidence | [test-and-record.md](test-and-record.md) |
| Begin implementation | [implementation.md](implementation.md) |

Context must precede audit and discovery. Applicable phase docs may be read
together before executing them; Browser depth is conditional.
