# Yoke Atlas

Operator-readable inventory of Yoke's agent-facing surfaces. Rendered by `python3 -m yoke_core.tools.atlas_render_docs render` from the Atlas integrity audit JSON.

_Audit generated_at: 2026-07-18T20:45:02Z_

## 1. Summary

- Function ids registered: **224**
- Internal dispatch-only functions without CLI adapters: **1**
- `yoke` CLI subcommands: **223** (223 carry usable `--help`)
- Operation tracker: **222 wrapped**, 74 permanent, 0 pending
- Skill-body recipes: 230 total (188 template-skipped, 0 failing)
- Recent field-notes inspected: 50
- Contradictions: **0 open** (of 2 tracked)

## 2. Wrapped operation roster

Wrapped `yoke <subcommand>` adapters: **223** (operation tracker confirms 222 wrapped rows).

| family | yoke form | function_id | help |
|---|---|---|---|
| agents | `yoke agents render check` | `agents.render.check` | ok |
| agents | `yoke agents render` | `agents.render.run` | ok |
| auth | `yoke auth set` | `auth.set.run` | ok |
| board | `yoke board data get` | `board.data.get` | ok |
| board | `yoke board rebuild` | `board.rebuild.run` | ok |
| charge | `yoke charge schedule` | `charge.schedule` | ok |
| claims | `yoke claims path activation-run` | `claims.path.activation_run` | ok |
| claims | `yoke claims path coordination-decision-build` | `claims.path.coordination_decision_build` | ok |
| claims | `yoke claims path get` | `claims.path.get` | ok |
| claims | `yoke claims path list` | `claims.path.list` | ok |
| claims | `yoke claims path register` | `claims.path.register` | ok |
| claims | `yoke claims path required-gate` | `claims.path.required_gate` | ok |
| claims | `yoke claims path widen` | `claims.path.widen` | ok |
| claims | `yoke claims work acquire` | `claims.work.acquire` | ok |
| claims | `yoke claims work holder-get` | `claims.work.holder_get` | ok |
| claims | `yoke claims work current` | `claims.work.holder_get` | ok |
| claims | `yoke claims work status` | `claims.work.holder_get` | ok |
| claims | `yoke claims work holder-list` | `claims.work.holder_list` | ok |
| claims | `yoke claims work release` | `claims.work.release` | ok |
| conduct | `yoke conduct epic proceed-triage-handoff` | `conduct.epic.proceed_triage_handoff` | ok |
| conduct | `yoke conduct epic-task update-status` | `conduct.epic_task.update_status` | ok |
| config | `yoke config example` | `config.example.run` | ok |
| config | `yoke config stamp-project-env` | `config.stamp_project_env.run` | ok |
| connection | `yoke connection remove` | `connection.remove.run` | ok |
| connection | `yoke connection set` | `connection.set.run` | ok |
| db | `yoke db read` | `db.read.run` | ok |
| db_claim | `yoke db-claim amend` | `db_claim.amend` | ok |
| deployment_flows | `yoke deployment-flows get` | `deployment_flows.get` | ok |
| deployment_flows | `yoke deployment-flows reconcile-project` | `deployment_flows.reconcile_project` | ok |
| deployment_flows | `yoke deployment-flows set-status` | `deployment_flows.set_status` | ok |
| deployment_flows | `yoke deployment-flows stages` | `deployment_flows.stages` | ok |
| deployment_flows | `yoke deployment-flows update-stages` | `deployment_flows.update_stages` | ok |
| deployment_runs | `yoke deployment-runs approve` | `deployment_runs.approve` | ok |
| deployment_runs | `yoke deployment-runs create` | `deployment_runs.create` | ok |
| deployment_runs | `yoke deployment-runs get` | `deployment_runs.get` | ok |
| deployment_runs | `yoke deployment-runs list` | `deployment_runs.list` | ok |
| deployment_runs | `yoke deployment-runs resolve-target-env` | `deployment_runs.resolve_target_env` | ok |
| deployment_runs | `yoke deployment-runs start-for-item` | `deployment_runs.start_for_item` | ok |
| deployment_runs | `yoke deployment-runs update` | `deployment_runs.update` | ok |
| doctor | `yoke doctor last-run get` | `doctor.last_run.get` | ok |
| doctor | `yoke doctor run` | `doctor.run.run` | ok |
| env | `yoke env use` | `env.use.run` | ok |
| ephemeral_env | `yoke ephemeral-env create` | `ephemeral_env.create` | ok |
| ephemeral_env | `yoke ephemeral-env update` | `ephemeral_env.update` | ok |
| epic_tasks | `yoke epic-tasks list` | `epic_tasks.list.run` | ok |
| events | `yoke events anomalies` | `events.anomalies.run` | ok |
| events | `yoke events count` | `events.count.run` | ok |
| events | `yoke events emit` | `events.emit` | ok |
| events | `yoke events query` | `events.query.run` | ok |
| events | `yoke events tail` | `events.tail.run` | ok |
| frontier | `yoke frontier list` | `frontier.list` | ok |
| github | `yoke github pr create` | `github.pr.create` | ok |
| github | `yoke github release create-next-tag` | `github.release.create_next_tag` | ok |
| github_actions | `yoke github-actions check-ci` | `github_actions.check_ci` | ok |
| github_actions | `yoke github-actions run jobs-count` | `github_actions.run.jobs_count` | ok |
| github_actions | `yoke github-actions jobs-count` | `github_actions.run.jobs_count` | ok |
| github_actions | `yoke github-actions runners status` | `github_actions.runners.status` | ok |
| github_actions | `yoke github-actions secret delete` | `github_actions.secret.delete` | ok |
| github_actions | `yoke github-actions secret set` | `github_actions.secret.set` | ok |
| github_actions | `yoke github-actions variable delete` | `github_actions.variable.delete` | ok |
| github_actions | `yoke github-actions variable get` | `github_actions.variable.get` | ok |
| github_actions | `yoke github-actions variable set` | `github_actions.variable.set` | ok |
| github_actions | `yoke github-actions wait-run` | `github_actions.wait_run` | ok |
| github_actions | `yoke github-actions poll` | `github_actions.wait_run` | ok |
| github_actions | `yoke github-actions workflow dispatch` | `github_actions.workflow.dispatch` | ok |
| github_actions | `yoke github-actions trigger` | `github_actions.workflow.dispatch` | ok |
| github_actions | `yoke github-actions workflow dispatch-once` | `github_actions.workflow.dispatch_once` | ok |
| github_actions | `yoke github-actions trigger-once` | `github_actions.workflow.dispatch_once` | ok |
| github_actions | `yoke github-actions workflow find-run` | `github_actions.workflow.find_run` | ok |
| github_actions | `yoke github-actions find-run` | `github_actions.workflow.find_run` | ok |
| hook | `yoke hook evaluate` | `hook.evaluate.run` | ok |
| identity | `yoke identity autojoin set` | `identity.autojoin.set` | ok |
| identity | `yoke identity invite create` | `identity.invite.create` | ok |
| identity | `yoke identity invite list` | `identity.invite.list` | ok |
| identity | `yoke identity invite revoke` | `identity.invite.revoke` | ok |
| identity | `yoke identity link set` | `identity.link.set` | ok |
| items | `yoke items create` | `items.create` | ok |
| items | `yoke items get` | `items.get.run` | ok |
| items | `yoke items github-sync` | `items.github_sync` | ok |
| items | `yoke items list` | `items.list.run` | ok |
| items | `yoke items progress-log append` | `items.progress_log.append` | ok |
| items | `yoke items scalar update` | `items.scalar.update` | ok |
| items | `yoke items search` | `items.search.run` | ok |
| items | `yoke items section delete` | `items.section.delete` | ok |
| items | `yoke items section get` | `items.section.get` | ok |
| items | `yoke items section upsert` | `items.section.upsert` | ok |
| items | `yoke items structured-field append-addendum` | `items.structured_field.append_addendum` | ok |
| items | `yoke items structured-field replace` | `items.structured_field.replace` | ok |
| items | `yoke items structured-field section-append` | `items.structured_field.section_append` | ok |
| items | `yoke items structured-field section-upsert` | `items.structured_field.section_upsert` | ok |
| lifecycle | `yoke lifecycle skip record-recoverable-substrate` | `lifecycle.skip.record_recoverable_substrate` | ok |
| lifecycle | `yoke lifecycle transition` | `lifecycle.transition.execute` | ok |
| onboard | `yoke onboard checklist init` | `onboard.checklist.init` | ok |
| onboard | `yoke onboard checklist` | `onboard.checklist.run` | ok |
| organizations | `yoke organizations get` | `organizations.get` | ok |
| ouroboros | `yoke ouroboros entry get` | `ouroboros.entry.get` | ok |
| ouroboros | `yoke ouroboros entry insert` | `ouroboros.entry.insert` | ok |
| ouroboros | `yoke ouroboros entry list` | `ouroboros.entry.list` | ok |
| ouroboros | `yoke ouroboros entry mark-archived` | `ouroboros.entry.mark_archived` | ok |
| ouroboros | `yoke ouroboros entry mark-reviewed` | `ouroboros.entry.mark_reviewed` | ok |
| ouroboros | `yoke ouroboros field-note append` | `ouroboros.field_note.append` | ok |
| ouroboros | `yoke ouroboros field-note get` | `ouroboros.field_note.get` | ok |
| ouroboros | `yoke ouroboros field-note list` | `ouroboros.field_note.list` | ok |
| ouroboros | `yoke ouroboros wrapup list` | `ouroboros.wrapup.list` | ok |
| ouroboros | `yoke ouroboros wrapup save` | `ouroboros.wrapup.save` | ok |
| packets | `yoke packets check` | `packets.check.run` | ok |
| packets | `yoke packets render` | `packets.render.run` | ok |
| path_claims | `yoke path-claims conflicts list` | `path_claims.conflicts.list` | ok |
| project | `yoke project artifacts refresh` | `project.artifacts.refresh` | ok |
| project | `yoke project install` | `project.install.run` | ok |
| project | `yoke project refresh` | `project.refresh.run` | ok |
| project | `yoke project register` | `project.register.run` | ok |
| project | `yoke project snapshot sync` | `project.snapshot.sync` | ok |
| project | `yoke project uninstall` | `project.uninstall.run` | ok |
| project_structure | `yoke project-structure command-definitions get` | `project_structure.command_definitions.get` | ok |
| project_structure | `yoke project-structure command-definitions list` | `project_structure.command_definitions.list` | ok |
| project_structure | `yoke project-structure deploy-defaults get` | `project_structure.deploy_defaults.get` | ok |
| project_structure | `yoke project-structure patch apply` | `project_structure.patch.apply` | ok |
| projects | `yoke projects capabilities list` | `projects.capabilities.list` | ok |
| projects | `yoke projects capability has` | `projects.capability.has` | ok |
| projects | `yoke projects capability-secret set` | `projects.capability_secret.set` | ok |
| projects | `yoke projects capability secret set` | `projects.capability_secret.set` | ok |
| projects | `yoke projects capability-settings get` | `projects.capability_settings.get` | ok |
| projects | `yoke projects capability-settings merge` | `projects.capability_settings.merge` | ok |
| projects | `yoke projects capability-settings set` | `projects.capability_settings.set` | ok |
| projects | `yoke projects checkout-context` | `projects.checkout_context.run` | ok |
| projects | `yoke projects create` | `projects.create` | ok |
| projects | `yoke projects environment-settings get` | `projects.environment_settings.get` | ok |
| projects | `yoke projects environment-settings merge` | `projects.environment_settings.merge` | ok |
| projects | `yoke projects get` | `projects.get` | ok |
| projects | `yoke projects github-binding bind` | `projects.github_binding.bind` | ok |
| projects | `yoke projects github-binding status` | `projects.github_binding.status` | ok |
| projects | `yoke projects github-binding unbind` | `projects.github_binding.unbind` | ok |
| projects | `yoke projects github-sync-mode repair` | `projects.github_sync_mode.repair` | ok |
| projects | `yoke projects infrastructure list` | `projects.infrastructure.list` | ok |
| projects | `yoke projects list` | `projects.list` | ok |
| projects | `yoke projects pulumi-stack-config get` | `projects.pulumi_stack_config.get` | ok |
| projects | `yoke projects pulumi-state checkpoint-import` | `projects.pulumi_state.checkpoint_import` | ok |
| projects | `yoke projects pulumi-state migrate` | `projects.pulumi_state.migrate` | ok |
| projects | `yoke projects resolve-by-github-repo` | `projects.resolve_by_github_repo` | ok |
| projects | `yoke projects update` | `projects.update` | ok |
| qa | `yoke qa artifact add` | `qa.artifact.add` | ok |
| qa | `yoke qa artifact presign` | `qa.artifact.presign` | ok |
| qa | `yoke qa browser-context get` | `qa.browser_context.get` | ok |
| qa | `yoke qa gate-summary` | `qa.gate_summary.run` | ok |
| qa | `yoke qa requirement add` | `qa.requirement.add` | ok |
| qa | `yoke qa requirement add-batch` | `qa.requirement.add_batch` | ok |
| qa | `yoke qa requirement auto-create-for-item` | `qa.requirement.auto_create_for_item` | ok |
| qa | `yoke qa requirement get` | `qa.requirement.get` | ok |
| qa | `yoke qa requirement list` | `qa.requirement.list` | ok |
| qa | `yoke qa requirement update` | `qa.requirement.update` | ok |
| qa | `yoke qa requirement waive` | `qa.requirement.waive` | ok |
| qa | `yoke qa run add` | `qa.run.add` | ok |
| qa | `yoke qa run complete` | `qa.run.complete` | ok |
| qa | `yoke qa run get` | `qa.run.get` | ok |
| qa | `yoke qa run list` | `qa.run.list` | ok |
| qa | `yoke qa run record-verdict` | `qa.run.record_verdict` | ok |
| qa | `yoke qa screenshot-evidence pending-count` | `qa.screenshot_evidence.pending_count` | ok |
| qa | `yoke qa screenshot-evidence satisfy` | `qa.screenshot_evidence.satisfy` | ok |
| readiness | `yoke readiness check` | `readiness.check.run` | ok |
| readiness | `yoke readiness prd-validate` | `readiness.prd_validate.run` | ok |
| readiness | `yoke readiness repair-claim-coverage` | `readiness.repair_claim_coverage` | ok |
| readiness | `yoke readiness repair-stale-count` | `readiness.repair_stale_count` | ok |
| scratch | `yoke scratch dispatch-inputs` | `scratch.dispatch_inputs` | ok |
| sessions | `yoke sessions begin` | `sessions.begin` | ok |
| sessions | `yoke sessions checkpoint` | `sessions.checkpoint` | ok |
| sessions | `yoke sessions checkpoint-read` | `sessions.checkpoint_read` | ok |
| sessions | `yoke sessions init` | `sessions.init` | ok |
| sessions | `yoke sessions list` | `sessions.list` | ok |
| sessions | `yoke sessions offer` | `sessions.offer` | ok |
| sessions | `yoke sessions ownership-guard` | `sessions.ownership_guard` | ok |
| sessions | `yoke sessions touch` | `sessions.touch` | ok |
| shepherd | `yoke shepherd caveat-disposition` | `shepherd.caveat_disposition.run` | ok |
| shepherd | `yoke shepherd dependency-add` | `shepherd.dependency_add.run` | ok |
| shepherd | `yoke shepherd dependency-list` | `shepherd.dependency_list.run` | ok |
| shepherd | `yoke shepherd dependency-remove` | `shepherd.dependency_remove.run` | ok |
| shepherd | `yoke shepherd dependency-update` | `shepherd.dependency_update.run` | ok |
| shepherd | `yoke shepherd verdict` | `shepherd.verdict.run` | ok |
| status | `yoke status` | `status.run` | ok |
| strategy | `yoke strategy carry candidate-set` | `strategy.carry.candidate_set` | ok |
| strategy | `yoke strategy carry mark` | `strategy.carry.mark` | ok |
| strategy | `yoke strategy carry register-new` | `strategy.carry.register_new` | ok |
| strategy | `yoke strategy carry summary` | `strategy.carry.summary` | ok |
| strategy | `yoke strategy checkpoint latest` | `strategy.checkpoint.latest` | ok |
| strategy | `yoke strategy checkpoint record` | `strategy.checkpoint.record` | ok |
| strategy | `yoke strategy doc archive` | `strategy.doc.archive` | ok |
| strategy | `yoke strategy doc create` | `strategy.doc.create` | ok |
| strategy | `yoke strategy doc get` | `strategy.doc.get` | ok |
| strategy | `yoke strategy doc list` | `strategy.doc.list` | ok |
| strategy | `yoke strategy doc replace` | `strategy.doc.replace` | ok |
| strategy | `yoke strategy doc unarchive` | `strategy.doc.unarchive` | ok |
| strategy | `yoke strategy ingest` | `strategy.ingest.run` | ok |
| strategy | `yoke strategy master-plan-check` | `strategy.master_plan_check.run` | ok |
| strategy | `yoke strategy render` | `strategy.render.run` | ok |
| strategy | `yoke strategy seed-defaults` | `strategy.seed_defaults.run` | ok |
| templates | `yoke templates fetch` | `templates.fetch.run` | ok |
| templates | `yoke templates list` | `templates.list.run` | ok |
| workflow_item | `yoke workflow-item epic-dispatch-chain advance` | `workflow_item.epic_dispatch_chain.advance` | ok |
| workflow_item | `yoke workflow-item epic-dispatch-chain get` | `workflow_item.epic_dispatch_chain.get` | ok |
| workflow_item | `yoke workflow-item epic-dispatch-chain list` | `workflow_item.epic_dispatch_chain.list` | ok |
| workflow_item | `yoke workflow-item epic-dispatch-chain refresh-activation` | `workflow_item.epic_dispatch_chain.refresh_activation` | ok |
| workflow_item | `yoke workflow-item epic-dispatch-chain update` | `workflow_item.epic_dispatch_chain.update` | ok |
| workflow_item | `yoke workflow-item epic-progress-note append` | `workflow_item.epic_progress_note.append` | ok |
| workflow_item | `yoke workflow-item epic-progress-note list` | `workflow_item.epic_progress_note.list` | ok |
| workflow_item | `yoke workflow-item epic-task add` | `workflow_item.epic_task.add` | ok |
| workflow_item | `yoke workflow-item epic-task body-get` | `workflow_item.epic_task.body_get` | ok |
| workflow_item | `yoke workflow-item epic-task body-replace` | `workflow_item.epic_task.body_replace` | ok |
| workflow_item | `yoke workflow-item epic-task file-add` | `workflow_item.epic_task.file_add` | ok |
| workflow_item | `yoke workflow-item epic-task get` | `workflow_item.epic_task.get` | ok |
| workflow_item | `yoke workflow-item epic-task history-insert` | `workflow_item.epic_task.history_insert` | ok |
| workflow_item | `yoke workflow-item epic-task metadata-update` | `workflow_item.epic_task.metadata_update` | ok |
| workflow_item | `yoke workflow-item epic-task reassign` | `workflow_item.epic_task.reassign` | ok |
| workflow_item | `yoke workflow-item epic-task remove` | `workflow_item.epic_task.remove` | ok |
| workflow_item | `yoke workflow-item epic-task review-get` | `workflow_item.epic_task.review_get` | ok |
| workflow_item | `yoke workflow-item epic-task review-insert` | `workflow_item.epic_task.review_insert` | ok |
| workflow_item | `yoke workflow-item epic-task review-list` | `workflow_item.epic_task.review_list` | ok |
| workflow_item | `yoke workflow-item epic-task review-seed` | `workflow_item.epic_task.review_seed` | ok |
| workflow_item | `yoke workflow-item epic-task simulation-get` | `workflow_item.epic_task.simulation_get` | ok |
| workflow_item | `yoke workflow-item epic-task simulation-upsert` | `workflow_item.epic_task.simulation_upsert` | ok |
| workflow_item | `yoke workflow-item epic-task split` | `workflow_item.epic_task.split` | ok |
| workflow_item | `yoke workflow-item epic-task submission-receipt-get` | `workflow_item.epic_task.submission_receipt_get` | ok |
| workflow_item | `yoke workflow-item epic-task update-status` | `workflow_item.epic_task.update_status` | ok |
| workflows | `yoke workflows definition get` | `workflows.definition.get` | ok |

## 3. Permanent command-shaped boundary roster

| family | shell_form | reason | source owner |
|---|---|---|---|
| aws | `yoke aws exec` | tool_shaped | — |
| board.art | `yoke board art variant create` | tool_shaped | — |
| checks.file_line | `yoke check file-line` | tool_shaped | — |
| claims.coordination_lease | `python3 -m yoke_core.api.service_client coordination-lease-acquire` | operator_break_glass | — |
| claims.coordination_lease | `python3 -m yoke_core.api.service_client coordination-lease-heartbeat` | operator_break_glass | — |
| claims.coordination_lease | `python3 -m yoke_core.api.service_client coordination-lease-list` | operator_break_glass | — |
| claims.coordination_lease | `python3 -m yoke_core.api.service_client coordination-lease-release` | operator_break_glass | — |
| claims.path | `python3 -m yoke_core.api.service_client path-claim-override` | operator_break_glass | — |
| claims.path | `python3 -m yoke_core.cli.db_router path-claims activate` | operator_break_glass | — |
| claims.path | `python3 -m yoke_core.cli.db_router path-claims amend` | operator_break_glass | — |
| claims.path | `python3 -m yoke_core.cli.db_router path-claims release` | operator_break_glass | — |
| core.local | `yoke core build` | tool_shaped | — |
| core.local | `yoke core logs` | tool_shaped | — |
| core.local | `yoke core start` | tool_shaped | — |
| core.local | `yoke core status` | tool_shaped | — |
| core.local | `yoke core stop` | tool_shaped | — |
| core.local | `yoke core upgrade` | tool_shaped | — |
| deployment_flows | `python3 -m yoke_core.domain.flow delete` | operator_break_glass | — |
| deployment_flows | `python3 -m yoke_core.domain.flow update-stages` | operator_break_glass | — |
| deployment_runs | `python3 -m yoke_core.domain.deploy_environment_bootstrap` | tool_shaped | — |
| deployment_runs | `python3 -m yoke_core.domain.deploy_ephemeral` | tool_shaped | — |
| deployment_runs | `python3 -m yoke_core.domain.deploy_pipeline` | tool_shaped | — |
| deployment_runs | `python3 -m yoke_core.domain.environment_bootstrap` | tool_shaped | — |
| deployment_runs | `python3 -m yoke_core.tools.verify_env_auth_boundary` | tool_shaped | — |
| deployment_runs | `yoke deployment-runs execute` | tool_shaped | — |
| dev | `yoke dev db-admin setup` | tool_shaped | — |
| dev | `yoke dev path-snapshot-prewarm` | tool_shaped | — |
| dev | `yoke dev setup` | tool_shaped | — |
| git | `yoke git post-commit` | tool_shaped | — |
| git | `yoke git pre-commit` | tool_shaped | — |
| github | `yoke github connect` | tool_shaped | — |
| github | `yoke github disconnect` | tool_shaped | — |
| github | `yoke github status` | tool_shaped | — |
| local_universe | `yoke init` | tool_shaped | — |
| local_universe.postgres | `yoke local-postgres start` | tool_shaped | — |
| local_universe.postgres | `yoke local-postgres status` | tool_shaped | — |
| local_universe.postgres | `yoke local-postgres stop` | tool_shaped | — |
| local_universe.ui | `yoke ui` | tool_shaped | — |
| local_universe.validate | `yoke universe validate` | tool_shaped | — |
| merge | `yoke merge audit` | tool_shaped | — |
| onboard | `yoke onboard project` | tool_shaped | — |
| onboard | `yoke onboard` | tool_shaped | — |
| project | `yoke project create` | tool_shaped | — |
| project | `yoke project import` | tool_shaped | — |
| pulumi | `yoke pulumi exec` | tool_shaped | packages/yoke-cli/src/yoke_cli/commands/adapters/pulumi.py; packages/yoke-core/src/yoke_core/tools/pulumi_exec.py |
| qa.browser | `yoke qa browser run` | tool_shaped | — |
| qa.browser | `yoke qa browser screenshot` | tool_shaped | — |
| qa.browser | `yoke qa browser setup` | tool_shaped | — |
| qa.browser | `yoke qa browser status` | tool_shaped | — |
| raw.sql | `python3 -m yoke_core.cli.db_router query` | operator_break_glass | — |
| resync | `yoke resync` | tool_shaped | — |
| runner_fleet | `yoke runner-fleet exec` | tool_shaped | — |
| schema | `yoke schema converge` | tool_shaped | — |
| self_host | `yoke self-host init` | tool_shaped | — |
| self_host.connect | `yoke connect` | tool_shaped | — |
| self_host.import | `yoke self-host import` | tool_shaped | — |
| sessions | `yoke sessions init` | tool_shaped | — |
| source_authority.export | `yoke source-authority export` | tool_shaped | — |
| source_authority.quiesce | `yoke source-authority quiesce` | tool_shaped | — |
| tools.atlas | `python3 -m yoke_core.tools.atlas_render_docs check` | tool_shaped | — |
| tools.atlas | `python3 -m yoke_core.tools.atlas_render_docs render` | tool_shaped | — |
| tools.module_source_path | `python3 -m yoke_core.tools.module_source_path` | tool_shaped | — |
| tools.watch | `python3 -m yoke_core.tools.watch_advance` | tool_shaped | — |
| tools.watch | `python3 -m yoke_core.tools.watch_doctor` | tool_shaped | — |
| tools.watch | `python3 -m yoke_core.tools.watch_inventory` | tool_shaped | — |
| tools.watch | `python3 -m yoke_core.tools.watch_lifecycle` | tool_shaped | — |
| tools.watch | `python3 -m yoke_core.tools.watch_merge` | tool_shaped | — |
| tools.watch | `python3 -m yoke_core.tools.watch_pytest` | tool_shaped | — |
| tools.watch | `python3 -m yoke_core.tools.watch_session_offer` | tool_shaped | — |
| tools.watch | `python3 -m yoke_core.tools.watch_tail` | tool_shaped | — |
| universe.export | `yoke universe export` | tool_shaped | — |
| universe.import | `yoke universe import` | tool_shaped | — |
| usher | `yoke usher reconcile-github` | tool_shaped | — |
| worktree | `python3 -m yoke_core.domain.worktree create` | tool_shaped | — |

## 4. Pending handler-registration roster

_No pending handler-registration rows._

## 5. Teaching coverage

| path glob | count |
|---|---|
| .agents/skills/yoke/**/*.md | 123 |
| packages/yoke-core/src/yoke_core/domain/schema_api_context*.py | 24 |
| runtime/agents/*.md | 8 |
| runtime/harness/claude/agents/yoke-*.md | 7 |
| runtime/harness/codex/agents/yoke-*.toml | 7 |

Lint modules inventoried: **1** (0 reference the field-note footer; 0 carry denial text).

## 6. Field-note hotspots

Recent field-notes inspected: **50** (read surface: `agent_facing`).

| agent | recent count |
|---|---|
| 2 | 50 |

## 7. Contradictions

| id | status | surface | live truth |
|---|---|---|---|
| claims-work-holder-get-flag-vs-positional | resolved | yoke claims work holder-get | live `yoke claims work holder-get` accepts positional <YOK-N> |
| function-inventory-empty-registry-mismatch | resolved | docs/function-inventory.md | yoke_function_registry.list_entries() is non-empty |

## 8. Next-slice recommendation

_No outstanding follow-ups — the harness has nothing to recommend._

## 9. Curl floor — the envelope shape under every family

Every registered function id above accepts the same `FunctionCallRequest` envelope at the active env's `/v1/functions/call`. The `yoke` CLI is the default surface; curl is the operator floor when no CLI is installed:

```bash
API=https://app.stage.upyoke.com/api/orgs/yoke-stage   # the active env's api_url
TOKEN_FILE=~/.yoke/secrets/stage.token

cat > /tmp/envelope.json <<'EOF'
{
  "function": "events.query.run",
  "request_id": "<uuid>",
  "actor": {"session_id": "<harness session id or omit>"},
  "target": {"kind": "global"},
  "payload": {"limit": 5}
}
EOF

curl -sS -X POST "$API/v1/functions/call" \
  -H "Authorization: Bearer $(cat $TOKEN_FILE)" \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/envelope.json
```

Swap `function`, `target`, and `payload` per family — the payload schema for any id is served at `GET /v1/functions/schema/{function_id}` and the full id inventory at `GET /v1/functions/registry`. The CLI grammar manifest (tokens, usage lines) is `GET /v1/cli/manifest`. Responses are typed `FunctionCallResponse` envelopes on both success and denial. The boundary overwrites envelope actor identity from the verified bearer token.
