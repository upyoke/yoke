# Project Configuration Function Catalog

Read [envelope and authority](functions.md) first. `none` means no dispatcher work-claim check; handler permissions still apply. Read command help for the live payload and serving floor.

## Registered functions

| Function id | Claim policy |
|---|---|
| `config.example.run` | `none` |
| `config.stamp_project_env.run` | `none` |
| `config.status.run` | `none` |
| `connection.remove.run` | `none` |
| `connection.set.run` | `none` |
| `env.list.run` | `none` |
| `env.use.run` | `none` |
| `onboard.checklist.init` | `none` |
| `onboard.checklist.run` | `none` |
| `packs.bundle.get` | `none` |
| `packs.bundle.render` | `none` |
| `packs.get.run` | `none` |
| `packs.list` | `none` |
| `packs.project.report` | `none` |
| `packs.relink.run` | `none` |
| `packs.update.run` | `none` |
| `project.git.bootstrap` | `none` |
| `project.install.run` | `none` |
| `project.refresh.run` | `none` |
| `project.register.run` | `none` |
| `project.snapshot.ensure_at` | `none` |
| `project.snapshot.sync` | `none` |
| `project.uninstall.run` | `none` |
| `project_structure.architecture_draft.get` | `none` |
| `project_structure.architecture_health.get` | `none` |
| `project_structure.deploy_defaults.get` | `none` |
| `project_structure.get` | `none` |
| `project_structure.patch.apply` | `none` |
| `projects.capabilities.list` | `none` |
| `projects.capability.has` | `none` |
| `projects.capability_secret.set` | `none` |
| `projects.capability_settings.get` | `none` |
| `projects.capability_settings.merge` | `none` |
| `projects.capability_settings.remove` | `none` |
| `projects.capability_settings.set` | `none` |
| `projects.checkout_context.run` | `none` |
| `projects.create` | `none` |
| `projects.environment.create` | `none` |
| `projects.environment.list` | `none` |
| `projects.environment.update` | `none` |
| `projects.environment_settings.get` | `none` |
| `projects.environment_settings.merge` | `none` |
| `projects.get` | `none` |
| `projects.github_binding.bind` | `none` |
| `projects.github_binding.lifecycle` | `none` |
| `projects.github_binding.status` | `none` |
| `projects.github_binding.unbind` | `none` |
| `projects.github_state.read` | `none` |
| `projects.github_sync_mode.repair` | `none` |
| `projects.github_sync_receipt.record` | `none` |
| `projects.infrastructure.list` | `none` |
| `projects.level_summary.get` | `none` |
| `projects.list` | `none` |
| `projects.pulumi_stack_config.get` | `none` |
| `projects.pulumi_state.checkpoint_import` | `none` |
| `projects.pulumi_state.migrate` | `none` |
| `projects.resolve_by_github_repo` | `none` |
| `projects.retire` | `none` |
| `projects.site.create` | `none` |
| `projects.unretire` | `none` |
| `projects.update` | `none` |
| `strategy.carry.candidate_set` | `none` |
| `strategy.carry.mark` | `none` |
| `strategy.carry.register_new` | `none` |
| `strategy.carry.summary` | `none` |
| `strategy.checkpoint.latest` | `none` |
| `strategy.checkpoint.record` | `none` |
| `strategy.claim.acquire` | `none` |
| `strategy.claim.break_glass_release` | `steering` |
| `strategy.claim.release` | `none` |
| `strategy.coordination.append` | `none` |
| `strategy.doc.archive` | `none` |
| `strategy.doc.create` | `none` |
| `strategy.doc.get` | `none` |
| `strategy.doc.list` | `none` |
| `strategy.doc.replace` | `none` |
| `strategy.doc.section_replace` | `none` |
| `strategy.doc.unarchive` | `none` |
| `strategy.doc_claim.acquire` | `none` |
| `strategy.doc_claim.list` | `none` |
| `strategy.doc_claim.release` | `none` |
| `strategy.execution.get` | `none` |
| `strategy.execution.link` | `none` |
| `strategy.ingest.run` | `none` |
| `strategy.master_plan_check.run` | `none` |
| `strategy.parent.set` | `none` |
| `strategy.render.run` | `none` |
| `strategy.revision.diff` | `none` |
| `strategy.revision.restore` | `none` |
| `strategy.seed_defaults.run` | `none` |
| `strategy.surface.get` | `none` |
| `strategy.surface.list` | `none` |
| `universe.level_capacity.get` | `none` |
| `universe.levels.get` | `none` |
| `universe.levels.set` | `none` |

## Project configuration and strategy

Project configuration writes use the target project's admin authority; an item
target supplies provenance, never substitutes for it. Structure patches apply
atomically. Architecture draft is a scan-derived proposal, including empty-tree
vocabulary; health derives coverage/violations from the same model computer used
by the board. Apply an operator-reviewed payload through the registered patch.

Site/environment create is idempotent by registered identity: an existing match
is unchanged, ownership mismatch refuses. Updates preserve id/site and change
only named fields. Settings use their narrow read/write surfaces; never dump
environment containers. Pack publishing is immutable; installed files and
project configuration keep their own authority. [Fleet policy](fleet-policy.md).

Strategy documents are DB rows; `.yoke/strategy/` is a gitignored render.
Every content write validates exactly one Summary and one State section with a
nonempty trimmed plain-text line. Unicode-character limits and normalized
headings come from `yoke_contracts.project_contract.strategy_doc_fields`, printed
by command help; State retains authored case/wording. Missing, duplicate, empty,
multiline or over-limit fields refuse before row/revision changes.

Create takes required separate summary/state fields and replaces body copies,
inserting after H1 (or at top). Replace and section replace validate the complete
result before CAS; bare field names and numeric limit suffixes match without
case sensitivity. Ingest validates every proposed document before any batch
write and retains its rendered header's CAS base. Restore validates history;
explicit field overrides repair legacy invalid content. Default seeding supplies
valid bounded fields even for long project names. Coordination append refuses
Summary/State and validates the complete resulting document for other sections.

```sh
yoke strategy doc create SLUG --summary TEXT --state TEXT --content-file PATH --target-root PATH
yoke strategy doc replace SLUG --content-file PATH --base-updated-at TS --target-root PATH
yoke strategy doc section-replace SLUG --heading Summary --content-file PATH --base-updated-at TS --target-root PATH
yoke strategy ingest SLUG --target-root PATH --dry-run
yoke strategy revision restore SLUG --revision <revision-number> --base-updated-at TS
```

Archived content stays stored until explicitly changed. Refusals report field,
count, limit and repair; successful writes normalize legacy headings. Render and
mutation receipts cover the edited slug only; JSON retains the full envelope.
