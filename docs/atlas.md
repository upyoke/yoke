# Yoke Atlas

Operator-readable inventory of Yoke's agent-facing surfaces. Rendered by `python3 -m yoke_core.tools.atlas_render_docs render` from the Atlas integrity audit JSON.

_Audit generated_at: 2026-08-28T20:38:16Z_

## 1. Summary

- Function ids registered: **438**
- Internal dispatch-only functions without CLI adapters: **86**
- `yoke` CLI subcommands: **365** (365 carry usable `--help`)
- Operation tracker: **342 wrapped**, 13 tool_cli, 126 permanent, 0 pending
- Skill-body recipes: 328 total (275 template-skipped, 0 failing)
- Recent field-notes inspected: 50
- Contradictions: **0 open** (of 2 tracked)

## 2. Wrapped operation roster

Wrapped dispatcher-backed `yoke <subcommand>` adapters: **342** (operation tracker confirms 342 wrapped rows).

| family | yoke form | function_id | help |
|---|---|---|---|
| board | `yoke board data get` | `board.data.get` | ok |
| board | `yoke board rebuild` | `board.rebuild.run` | ok |
| charge | `yoke charge schedule` | `charge.schedule` | ok |
| claims | `yoke claims coordination-claim list` | `claims.coordination_claim.list` | ok |
| claims | `yoke coordination-claim list` | `claims.coordination_claim.list` | ok |
| claims | `yoke claims path activation-run` | `claims.path.activation_run` | ok |
| claims | `yoke claims path amend` | `claims.path.amend` | ok |
| claims | `yoke claims path coordination-decision-build` | `claims.path.coordination_decision_build` | ok |
| claims | `yoke claims path get` | `claims.path.get` | ok |
| claims | `yoke claims path list` | `claims.path.list` | ok |
| claims | `yoke claims path override` | `claims.path.override` | ok |
| claims | `yoke claims path register` | `claims.path.register` | ok |
| claims | `yoke claims path required-gate` | `claims.path.required_gate` | ok |
| claims | `yoke claims path widen` | `claims.path.widen` | ok |
| claims | `yoke claims steering acquire` | `claims.steering.acquire` | ok |
| claims | `yoke claims steering list` | `claims.steering.list` | ok |
| claims | `yoke claims steering release` | `claims.steering.release` | ok |
| claims | `yoke claims work acquire` | `claims.work.acquire` | ok |
| claims | `yoke claims work holder-get` | `claims.work.holder_get` | ok |
| claims | `yoke claims work current` | `claims.work.holder_get` | ok |
| claims | `yoke claims work status` | `claims.work.holder_get` | ok |
| claims | `yoke claims work holder-list` | `claims.work.holder_list` | ok |
| claims | `yoke claims work release` | `claims.work.release` | ok |
| conduct | `yoke conduct epic proceed-triage-handoff` | `conduct.epic.proceed_triage_handoff` | ok |
| conduct | `yoke conduct epic-task update-status` | `conduct.epic_task.update_status` | ok |
| db | `yoke db read` | `db.read.run` | ok |
| db_claim | `yoke db-claim amend` | `db_claim.amend` | ok |
| db_claim | `yoke db-claim prose-check` | `db_claim.prose_check` | ok |
| decision_requests | `yoke decision-requests resolve` | `decision_requests.resolve` | ok |
| deployment_flows | `yoke deployment-flows create` | `deployment_flows.create` | ok |
| deployment_flows | `yoke deployment-flows describe` | `deployment_flows.describe` | ok |
| deployment_flows | `yoke deployment-flows get` | `deployment_flows.get` | ok |
| deployment_flows | `yoke deployment-flows list` | `deployment_flows.list` | ok |
| deployment_flows | `yoke deployment-flows set-status` | `deployment_flows.set_status` | ok |
| deployment_flows | `yoke deployment-flows stages` | `deployment_flows.stages` | ok |
| deployment_flows | `yoke deployment-flows update-stages` | `deployment_flows.update_stages` | ok |
| deployment_runs | `yoke deployment-runs approve` | `deployment_runs.approve` | ok |
| deployment_runs | `yoke deployment-runs create` | `deployment_runs.create` | ok |
| deployment_runs | `yoke deployment-runs find-by-item` | `deployment_runs.find_by_item` | ok |
| deployment_runs | `yoke deployment-runs get` | `deployment_runs.get` | ok |
| deployment_runs | `yoke deployment-runs list` | `deployment_runs.list` | ok |
| deployment_runs | `yoke deployment-runs project-snapshot` | `deployment_runs.project_snapshot` | ok |
| deployment_runs | `yoke deployment-runs resolve-target` | `deployment_runs.resolve_target` | ok |
| deployment_runs | `yoke deployment-runs stages` | `deployment_runs.stages` | ok |
| deployment_runs | `yoke deployment-runs start-for-item` | `deployment_runs.start_for_item` | ok |
| deployment_runs | `yoke deployment-runs terminalize` | `deployment_runs.terminalize` | ok |
| deployment_runs | `yoke deployment-runs update` | `deployment_runs.update` | ok |
| direct_workflow | `yoke direct-workflow blitz survey` | `direct_workflow.blitz.survey` | ok |
| direct_workflow | `yoke direct-workflow conflict-survey status` | `direct_workflow.conflict_survey.status` | ok |
| direct_workflow | `yoke direct-workflow dash escalate` | `direct_workflow.dash.escalate` | ok |
| direct_workflow | `yoke direct-workflow dash evidence` | `direct_workflow.dash.evidence` | ok |
| direct_workflow | `yoke direct-workflow dash survey` | `direct_workflow.dash.survey` | ok |
| doctor | `yoke doctor last-run get` | `doctor.last_run.get` | ok |
| doctor | `yoke doctor run` | `doctor.run.run` | ok |
| ephemeral_env | `yoke ephemeral-env create` | `ephemeral_env.create` | ok |
| ephemeral_env | `yoke ephemeral-env get` | `ephemeral_env.get` | ok |
| ephemeral_env | `yoke ephemeral-env update` | `ephemeral_env.update` | ok |
| epic_tasks | `yoke epic-tasks list` | `epic_tasks.list.run` | ok |
| events | `yoke events anomalies` | `events.anomalies.run` | ok |
| events | `yoke events count` | `events.count.run` | ok |
| events | `yoke events emit` | `events.emit` | ok |
| events | `yoke events query` | `events.query.run` | ok |
| events | `yoke events tail` | `events.tail.run` | ok |
| frontier | `yoke frontier list` | `frontier.list` | ok |
| github | `yoke github merge-queue apply` | `github.merge_queue.apply` | ok |
| github | `yoke github pr create` | `github.pr.create` | ok |
| github | `yoke github release create-next-tag` | `github.release.create_next_tag` | ok |
| github_actions | `yoke github-actions check-ci` | `github_actions.check_ci` | ok |
| github_actions | `yoke github-actions failed-log` | `github_actions.failed_log` | ok |
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
| harness | `yoke harness machine-report upsert` | `harness.machine_report.upsert` | ok |
| hook | `yoke hook evaluate` | `hook.evaluate.run` | ok |
| identity | `yoke identity invite create` | `identity.invite.create` | ok |
| identity | `yoke identity invite list` | `identity.invite.list` | ok |
| identity | `yoke identity invite revoke` | `identity.invite.revoke` | ok |
| identity | `yoke identity link set` | `identity.link.set` | ok |
| inbox | `yoke inbox list` | `inbox.list` | ok |
| item_worktrees | `yoke item-worktrees create` | `item_worktrees.create` | ok |
| item_worktrees | `yoke item-worktrees get` | `item_worktrees.get` | ok |
| item_worktrees | `yoke item-worktrees list` | `item_worktrees.list` | ok |
| item_worktrees | `yoke item-worktrees path-record` | `item_worktrees.path_record` | ok |
| item_worktrees | `yoke item-worktrees release` | `item_worktrees.release` | ok |
| items | `yoke items block` | `items.block.run` | ok |
| items | `yoke items create` | `items.create` | ok |
| items | `yoke dash` | `items.create` | ok |
| items | `yoke items detail get` | `items.detail.get` | ok |
| items | `yoke items freeze` | `items.freeze.run` | ok |
| items | `yoke items get` | `items.get.run` | ok |
| items | `yoke items github-sync` | `items.github_sync` | ok |
| items | `yoke items list` | `items.list.run` | ok |
| items | `yoke items merge-provenance operator-correct` | `items.merge_provenance.operator_correct` | ok |
| items | `yoke items overview list` | `items.overview.list` | ok |
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
| items | `yoke items thaw` | `items.thaw.run` | ok |
| items | `yoke items unblock` | `items.unblock.run` | ok |
| lifecycle | `yoke lifecycle repair-status` | `lifecycle.repair_status.execute` | ok |
| lifecycle | `yoke lifecycle skip record-recoverable-substrate` | `lifecycle.skip.record_recoverable_substrate` | ok |
| lifecycle | `yoke lifecycle transition` | `lifecycle.transition.execute` | ok |
| migration | `yoke migration content-identity verify` | `migration.content_identity.verify` | ok |
| onboard | `yoke onboard checklist init` | `onboard.checklist.init` | ok |
| onboard | `yoke onboard checklist` | `onboard.checklist.run` | ok |
| organizations | `yoke organizations domain set` | `organizations.domain.set` | ok |
| organizations | `yoke organizations get` | `organizations.get` | ok |
| organizations | `yoke organizations settings get` | `organizations.settings.get` | ok |
| organizations | `yoke organizations settings merge` | `organizations.settings.merge` | ok |
| ouroboros | `yoke ouroboros entry get` | `ouroboros.entry.get` | ok |
| ouroboros | `yoke ouroboros entry insert` | `ouroboros.entry.insert` | ok |
| ouroboros | `yoke ouroboros entry list` | `ouroboros.entry.list` | ok |
| ouroboros | `yoke ouroboros entry mark-archived` | `ouroboros.entry.mark_archived` | ok |
| ouroboros | `yoke ouroboros entry mark-reviewed` | `ouroboros.entry.mark_reviewed` | ok |
| ouroboros | `yoke ouroboros field-note append` | `ouroboros.field_note.append` | ok |
| ouroboros | `yoke ouroboros field-note get` | `ouroboros.field_note.get` | ok |
| ouroboros | `yoke ouroboros field-note list` | `ouroboros.field_note.list` | ok |
| ouroboros | `yoke ouroboros field-note promote` | `ouroboros.field_note.promote` | ok |
| overview | `yoke overview activation get` | `overview.activation.get` | ok |
| packs | `yoke packs list` | `packs.list` | ok |
| path_claims | `yoke path-claims conflicts list` | `path_claims.conflicts.list` | ok |
| project | `yoke project snapshot sync` | `project.snapshot.sync` | ok |
| project_structure | `yoke project-structure architecture-draft get` | `project_structure.architecture_draft.get` | ok |
| project_structure | `yoke project-structure architecture-health get` | `project_structure.architecture_health.get` | ok |
| project_structure | `yoke project-structure deploy-defaults get` | `project_structure.deploy_defaults.get` | ok |
| project_structure | `yoke project-structure get` | `project_structure.get` | ok |
| project_structure | `yoke project-structure patch apply` | `project_structure.patch.apply` | ok |
| projects | `yoke projects capabilities list` | `projects.capabilities.list` | ok |
| projects | `yoke projects capability has` | `projects.capability.has` | ok |
| projects | `yoke projects capability-secret set` | `projects.capability_secret.set` | ok |
| projects | `yoke projects capability secret set` | `projects.capability_secret.set` | ok |
| projects | `yoke projects capability-settings get` | `projects.capability_settings.get` | ok |
| projects | `yoke projects capability-settings merge` | `projects.capability_settings.merge` | ok |
| projects | `yoke projects capability-settings remove` | `projects.capability_settings.remove` | ok |
| projects | `yoke projects capability-settings set` | `projects.capability_settings.set` | ok |
| projects | `yoke projects checkout-context` | `projects.checkout_context.run` | ok |
| projects | `yoke projects create` | `projects.create` | ok |
| projects | `yoke projects environment create` | `projects.environment.create` | ok |
| projects | `yoke projects environment update` | `projects.environment.update` | ok |
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
| projects | `yoke projects site create` | `projects.site.create` | ok |
| projects | `yoke projects update` | `projects.update` | ok |
| qa | `yoke qa activity list` | `qa.activity.list` | ok |
| qa | `yoke qa artifact add` | `qa.artifact.add` | ok |
| qa | `yoke qa artifact presign` | `qa.artifact.presign` | ok |
| qa | `yoke qa artifact read` | `qa.artifact.read` | ok |
| qa | `yoke qa browser-context get` | `qa.browser_context.get` | ok |
| qa | `yoke qa gate-summary` | `qa.gate_summary.run` | ok |
| qa | `yoke qa item-plan attach` | `qa.item_plan.attach` | ok |
| qa | `yoke qa method get` | `qa.method.get` | ok |
| qa | `yoke qa method list` | `qa.method.list` | ok |
| qa | `yoke qa no-tests attest` | `qa.no_tests.attest` | ok |
| qa | `yoke qa no-tests clear` | `qa.no_tests.clear` | ok |
| qa | `yoke qa plan create` | `qa.plan.create` | ok |
| qa | `yoke qa plan edit` | `qa.plan.edit` | ok |
| qa | `yoke qa plan get` | `qa.plan.get` | ok |
| qa | `yoke qa plan list` | `qa.plan.list` | ok |
| qa | `yoke qa plan materialize` | `qa.plan.materialize` | ok |
| qa | `yoke qa plan rematerialize` | `qa.plan.rematerialize` | ok |
| qa | `yoke qa plan-cases replace` | `qa.plan_cases.replace` | ok |
| qa | `yoke qa project-default set` | `qa.project_default.set` | ok |
| qa | `yoke qa project-default unset` | `qa.project_default.unset` | ok |
| qa | `yoke qa project-method register` | `qa.project_method.register` | ok |
| qa | `yoke qa registered-command set` | `qa.registered_command.set` | ok |
| qa | `yoke qa requirement add` | `qa.requirement.add` | ok |
| qa | `yoke qa requirement add-batch` | `qa.requirement.add_batch` | ok |
| qa | `yoke qa requirement get` | `qa.requirement.get` | ok |
| qa | `yoke qa requirement list` | `qa.requirement.list` | ok |
| qa | `yoke qa requirement update` | `qa.requirement.update` | ok |
| qa | `yoke qa requirement waive` | `qa.requirement.waive` | ok |
| qa | `yoke qa run add` | `qa.run.add` | ok |
| qa | `yoke qa run complete` | `qa.run.complete` | ok |
| qa | `yoke qa run get` | `qa.run.get` | ok |
| qa | `yoke qa run list` | `qa.run.list` | ok |
| qa | `yoke qa run record-verdict` | `qa.run.record_verdict` | ok |
| readiness | `yoke readiness check` | `readiness.check.run` | ok |
| readiness | `yoke readiness prd-validate` | `readiness.prd_validate.run` | ok |
| readiness | `yoke readiness repair-claim-coverage` | `readiness.repair_claim_coverage` | ok |
| readiness | `yoke readiness repair-stale-count` | `readiness.repair_stale_count` | ok |
| release_pin | `yoke release-pin record` | `release_pin.record` | ok |
| session_control | `yoke session-control keepalive hold` | `session_control.keepalive.hold` | ok |
| session_control | `yoke sessions keepalive hold` | `session_control.keepalive.hold` | ok |
| session_control | `yoke session-control keepalive release` | `session_control.keepalive.release` | ok |
| session_control | `yoke sessions keepalive release` | `session_control.keepalive.release` | ok |
| session_control | `yoke session-control launch cancel` | `session_control.launch.cancel` | ok |
| session_control | `yoke session-control launch create` | `session_control.launch.create` | ok |
| session_control | `yoke sessions create` | `session_control.launch.create` | ok |
| session_control | `yoke session-control launch get` | `session_control.launch.get` | ok |
| session_control | `yoke session-control launch list` | `session_control.launch.list` | ok |
| session_control | `yoke session-control launch preview` | `session_control.launch.preview` | ok |
| session_control | `yoke session-control launch reconcile` | `session_control.launch.reconcile` | ok |
| session_control | `yoke session-control launch retry` | `session_control.launch.retry` | ok |
| session_control | `yoke session-control message acknowledge` | `session_control.message.acknowledge` | ok |
| session_control | `yoke messages ack` | `session_control.message.acknowledge` | ok |
| session_control | `yoke messages acknowledge` | `session_control.message.acknowledge` | ok |
| session_control | `yoke session-control message cancel` | `session_control.message.cancel` | ok |
| session_control | `yoke messages cancel` | `session_control.message.cancel` | ok |
| session_control | `yoke session-control message get` | `session_control.message.get` | ok |
| session_control | `yoke messages get` | `session_control.message.get` | ok |
| session_control | `yoke messages status` | `session_control.message.get` | ok |
| session_control | `yoke session-control message list` | `session_control.message.list` | ok |
| session_control | `yoke messages list` | `session_control.message.list` | ok |
| session_control | `yoke session-control message preview` | `session_control.message.preview` | ok |
| session_control | `yoke session-control message send` | `session_control.message.send` | ok |
| session_control | `yoke messages send` | `session_control.message.send` | ok |
| session_control | `yoke say` | `session_control.message.send` | ok |
| session_control | `yoke session-control qualification open` | `session_control.qualification.open` | ok |
| session_control | `yoke session-control session terminate` | `session_control.session.terminate` | ok |
| session_control | `yoke sessions terminate` | `session_control.session.terminate` | ok |
| session_control | `yoke session-control session wake` | `session_control.session.wake` | ok |
| session_control | `yoke session-control surface-policy disable` | `session_control.surface_policy.disable` | ok |
| session_control | `yoke session-control surface-policy enable` | `session_control.surface_policy.enable` | ok |
| session_control | `yoke session-control surface-policy list` | `session_control.surface_policy.list` | ok |
| sessions | `yoke sessions begin` | `sessions.begin` | ok |
| sessions | `yoke sessions checkpoint` | `sessions.checkpoint` | ok |
| sessions | `yoke sessions checkpoint-read` | `sessions.checkpoint_read` | ok |
| sessions | `yoke sessions end-if-empty` | `sessions.end_if_empty` | ok |
| sessions | `yoke sessions identity` | `sessions.identity` | ok |
| sessions | `yoke sessions list` | `sessions.list` | ok |
| sessions | `yoke sessions offer` | `sessions.offer` | ok |
| sessions | `yoke sessions ownership-guard` | `sessions.ownership_guard` | ok |
| sessions | `yoke sessions reclaim-stale` | `sessions.reclaim_stale` | ok |
| sessions | `yoke sessions touch` | `sessions.touch` | ok |
| shepherd | `yoke shepherd caveat-disposition` | `shepherd.caveat_disposition.run` | ok |
| shepherd | `yoke shepherd dependency-add` | `shepherd.dependency_add.run` | ok |
| shepherd | `yoke shepherd dependency-list` | `shepherd.dependency_list.run` | ok |
| shepherd | `yoke shepherd dependency-remove` | `shepherd.dependency_remove.run` | ok |
| shepherd | `yoke shepherd dependency-update` | `shepherd.dependency_update.run` | ok |
| shepherd | `yoke shepherd verdict` | `shepherd.verdict.run` | ok |
| steering | `yoke steering report get` | `steering.report.get` | ok |
| strategy | `yoke strategy carry candidate-set` | `strategy.carry.candidate_set` | ok |
| strategy | `yoke strategy carry mark` | `strategy.carry.mark` | ok |
| strategy | `yoke strategy carry register-new` | `strategy.carry.register_new` | ok |
| strategy | `yoke strategy carry summary` | `strategy.carry.summary` | ok |
| strategy | `yoke strategy checkpoint latest` | `strategy.checkpoint.latest` | ok |
| strategy | `yoke strategy checkpoint record` | `strategy.checkpoint.record` | ok |
| strategy | `yoke strategy claim acquire` | `strategy.claim.acquire` | ok |
| strategy | `yoke strategy claim break-glass-release` | `strategy.claim.break_glass_release` | ok |
| strategy | `yoke strategy claim release` | `strategy.claim.release` | ok |
| strategy | `yoke strategy coordination append` | `strategy.coordination.append` | ok |
| strategy | `yoke strategy doc archive` | `strategy.doc.archive` | ok |
| strategy | `yoke strategy doc create` | `strategy.doc.create` | ok |
| strategy | `yoke strategy doc get` | `strategy.doc.get` | ok |
| strategy | `yoke strategy doc list` | `strategy.doc.list` | ok |
| strategy | `yoke strategy doc replace` | `strategy.doc.replace` | ok |
| strategy | `yoke strategy doc unarchive` | `strategy.doc.unarchive` | ok |
| strategy | `yoke strategy doc-claim acquire` | `strategy.doc_claim.acquire` | ok |
| strategy | `yoke strategy doc-claim list` | `strategy.doc_claim.list` | ok |
| strategy | `yoke strategy doc-claim release` | `strategy.doc_claim.release` | ok |
| strategy | `yoke strategy execution get` | `strategy.execution.get` | ok |
| strategy | `yoke strategy execution link` | `strategy.execution.link` | ok |
| strategy | `yoke strategy ingest` | `strategy.ingest.run` | ok |
| strategy | `yoke strategy master-plan-check` | `strategy.master_plan_check.run` | ok |
| strategy | `yoke strategy parent set` | `strategy.parent.set` | ok |
| strategy | `yoke strategy render` | `strategy.render.run` | ok |
| strategy | `yoke strategy revision diff` | `strategy.revision.diff` | ok |
| strategy | `yoke strategy revision restore` | `strategy.revision.restore` | ok |
| strategy | `yoke strategy seed-defaults` | `strategy.seed_defaults.run` | ok |
| strategy | `yoke strategy surface get` | `strategy.surface.get` | ok |
| strategy | `yoke strategy surface list` | `strategy.surface.list` | ok |
| test_machine | `yoke test-machine get` | `test_machine.get` | ok |
| test_machine | `yoke test-machine list` | `test_machine.list` | ok |
| test_machine | `yoke test-machine settings-replace` | `test_machine.settings_replace` | ok |
| test_machine | `yoke test-machine verify` | `test_machine.verify` | ok |
| workflow | `yoke workflow execution-instruction create` | `workflow.execution_instruction.create` | ok |
| workflow | `yoke workflow execution-instruction delete` | `workflow.execution_instruction.delete` | ok |
| workflow | `yoke workflow execution-instruction list` | `workflow.execution_instruction.list` | ok |
| workflow | `yoke workflow execution-instruction resolve` | `workflow.execution_instruction.resolve` | ok |
| workflow | `yoke workflow execution-instruction set-scope` | `workflow.execution_instruction.set_scope` | ok |
| workflow | `yoke workflow execution-instruction update` | `workflow.execution_instruction.update` | ok |
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
| workflow_item | `yoke workflow-item epic-task scope-finalize` | `workflow_item.epic_task.scope_finalize` | ok |
| workflow_item | `yoke workflow-item epic-task scope-no-files` | `workflow_item.epic_task.scope_no_files` | ok |
| workflow_item | `yoke workflow-item epic-task scope-reopen` | `workflow_item.epic_task.scope_reopen` | ok |
| workflow_item | `yoke workflow-item epic-task scope-repair-legacy` | `workflow_item.epic_task.scope_repair_legacy` | ok |
| workflow_item | `yoke workflow-item epic-task simulation-get` | `workflow_item.epic_task.simulation_get` | ok |
| workflow_item | `yoke workflow-item epic-task simulation-upsert` | `workflow_item.epic_task.simulation_upsert` | ok |
| workflow_item | `yoke workflow-item epic-task split` | `workflow_item.epic_task.split` | ok |
| workflow_item | `yoke workflow-item epic-task submission-receipt-get` | `workflow_item.epic_task.submission_receipt_get` | ok |
| workflow_item | `yoke workflow-item epic-task update-status` | `workflow_item.epic_task.update_status` | ok |
| workflows | `yoke workflows approval-defaults publish` | `workflows.approval_defaults.publish` | ok |
| workflows | `yoke workflows current set` | `workflows.current.set` | ok |
| workflows | `yoke workflows definition get` | `workflows.definition.get` | ok |
| workflows | `yoke workflows delivery-default set` | `workflows.delivery_default.set` | ok |
| workflows | `yoke workflows item get` | `workflows.item.get` | ok |
| workflows | `yoke workflows item migrate` | `workflows.item.migrate` | ok |
| workflows | `yoke workflows mechanics get` | `workflows.mechanics.get` | ok |
| workflows | `yoke workflows policy-defaults publish` | `workflows.policy_defaults.publish` | ok |
| workflows | `yoke workflows testing-default set` | `workflows.testing_default.set` | ok |
| workflows | `yoke workflows version get` | `workflows.version.get` | ok |
| workflows | `yoke workflows version list` | `workflows.version.list` | ok |

## 3. Tool-shaped CLI roster

First-class local `yoke` adapters that run subprocess tools without a dispatcher function id.

| family | yoke form | reason |
|---|---|---|
| tools.advance_implementation_entry | `yoke advance implementation-entry` | tool_shaped |
| tools.release_pin | `yoke release-pin verify` | tool_shaped |
| tools.ruff_changed | `yoke dev ruff-changed` | tool_shaped |
| tools.source_dev_run | `yoke dev run` | tool_shaped |
| tools.watch | `yoke watch ci-run` | tool_shaped |
| tools.watch | `yoke watch deploy` | tool_shaped |
| tools.watch | `yoke watch doctor` | tool_shaped |
| tools.watch | `yoke watch fleet` | tool_shaped |
| tools.watch | `yoke watch merge` | tool_shaped |
| tools.watch | `yoke watch preflight` | tool_shaped |
| tools.watch | `yoke watch pytest` | tool_shaped |
| tools.watch | `yoke watch qa-case` | tool_shaped |
| tools.watch | `yoke watch qa-plan` | tool_shaped |

## 4. Permanent command-shaped boundary roster

| family | shell_form | reason | source owner |
|---|---|---|---|
| agents.render | `yoke agents render check` | tool_shaped | — |
| agents.render | `yoke agents render` | tool_shaped | — |
| auth | `yoke auth set` | tool_shaped | — |
| aws | `yoke aws admin-link` | tool_shaped | — |
| aws | `yoke aws exec` | tool_shaped | — |
| board.art | `yoke board art variant create` | tool_shaped | — |
| checks.file_line | `yoke check file-line` | tool_shaped | — |
| claims.coordination_claim | `python3 -m yoke_core.api.service_client coordination-claim-acquire` | operator_break_glass | — |
| claims.coordination_claim | `python3 -m yoke_core.api.service_client coordination-claim-heartbeat` | operator_break_glass | — |
| claims.coordination_claim | `python3 -m yoke_core.api.service_client coordination-claim-list` | operator_break_glass | — |
| claims.coordination_claim | `python3 -m yoke_core.api.service_client coordination-claim-release` | operator_break_glass | — |
| claims.path | `python3 -m yoke_core.api.service_client path-claim-override` | operator_break_glass | — |
| claims.path | `python3 -m yoke_core.cli.db_router path-claims activate` | operator_break_glass | — |
| claims.path | `python3 -m yoke_core.cli.db_router path-claims amend` | operator_break_glass | — |
| claims.path | `python3 -m yoke_core.cli.db_router path-claims release` | operator_break_glass | — |
| claims.work | `python3 -m yoke_core.api.service_client claim-release` | operator_break_glass | — |
| config | `yoke config example` | tool_shaped | — |
| config | `yoke config stamp-project-env` | tool_shaped | — |
| config | `yoke config status` | tool_shaped | — |
| connection | `yoke connection remove` | tool_shaped | — |
| connection | `yoke connection set` | tool_shaped | — |
| coordination_claim | `yoke coordination-claim release` | operator_break_glass | — |
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
| direct_workflow.worktree | `yoke direct-workflow worktree prepare` | tool_shaped | — |
| env | `yoke env list` | tool_shaped | — |
| env | `yoke env use` | tool_shaped | — |
| git | `yoke git post-commit` | tool_shaped | — |
| git | `yoke git pre-commit` | tool_shaped | — |
| github | `yoke github connect` | tool_shaped | — |
| github | `yoke github disconnect` | tool_shaped | — |
| github | `yoke github status` | tool_shaped | — |
| install_bundle.sync | `python3 -m yoke_core.domain.install_bundle_tree_sync sync` | tool_shaped | — |
| lint.config | `yoke lint config show` | tool_shaped | — |
| local.demo | `yoke local demo seed` | tool_shaped | — |
| local_universe | `yoke init` | tool_shaped | — |
| local_universe.postgres | `yoke local-postgres start` | tool_shaped | — |
| local_universe.postgres | `yoke local-postgres status` | tool_shaped | — |
| local_universe.postgres | `yoke local-postgres stop` | tool_shaped | — |
| local_universe.ui | `yoke ui` | tool_shaped | — |
| local_universe.validate | `yoke universe validate` | tool_shaped | — |
| merge | `yoke merge audit` | tool_shaped | — |
| merge.item | `yoke merge item` | tool_shaped | — |
| migration.apply | `yoke migration rehearse` | tool_shaped | — |
| onboard | `yoke onboard project` | tool_shaped | — |
| onboard | `yoke onboard` | tool_shaped | — |
| packets | `yoke packets budget get` | tool_shaped | — |
| packets | `yoke packets check` | tool_shaped | — |
| packets | `yoke packets render` | tool_shaped | — |
| packs | `yoke packs get` | tool_shaped | — |
| packs | `yoke packs relink` | tool_shaped | — |
| packs | `yoke packs update` | tool_shaped | — |
| path | `yoke path check` | tool_shaped | — |
| path | `yoke path fix` | tool_shaped | — |
| path | `yoke path verify` | tool_shaped | — |
| path_integrity | `python3 -m yoke_core.domain.path_integrity verify` | operator_break_glass | — |
| project | `yoke project create` | tool_shaped | — |
| project | `yoke project import` | tool_shaped | — |
| project | `yoke project install` | tool_shaped | — |
| project | `yoke project refresh` | tool_shaped | — |
| project | `yoke project register` | tool_shaped | — |
| project | `yoke project uninstall` | tool_shaped | — |
| pulumi | `yoke pulumi exec` | tool_shaped | packages/yoke-cli/src/yoke_cli/commands/adapters/pulumi.py; packages/yoke-core/src/yoke_core/tools/pulumi_exec.py |
| qa.browser | `yoke qa browser screenshot` | tool_shaped | — |
| qa.browser | `yoke qa browser setup` | tool_shaped | — |
| qa.browser | `yoke qa browser status` | tool_shaped | — |
| qa.browser | `yoke qa browser step` | tool_shaped | — |
| qa.case | `yoke qa case run` | tool_shaped | — |
| qa.mission | `yoke qa mission host-command` | tool_shaped | — |
| qa.plan | `yoke qa plan abort` | tool_shaped | — |
| qa.plan | `yoke qa plan review-submit` | tool_shaped | — |
| qa.plan | `yoke qa plan run` | tool_shaped | — |
| raw.sql | `python3 -m yoke_core.cli.db_router query` | operator_break_glass | — |
| resync | `yoke resync` | tool_shaped | — |
| runner_fleet | `yoke runner-fleet exec` | tool_shaped | — |
| schema | `yoke schema converge` | tool_shaped | — |
| scratch | `yoke scratch dispatch-inputs` | tool_shaped | — |
| self_host | `yoke self-host init` | tool_shaped | — |
| self_host.connect | `yoke connect` | tool_shaped | — |
| self_host.import | `yoke self-host import` | tool_shaped | — |
| session_control.acceptance | `yoke session-control acceptance run` | tool_shaped | — |
| session_control.relay | `yoke relay diagnostic` | tool_shaped | — |
| session_control.relay | `yoke relay install` | tool_shaped | — |
| session_control.relay | `yoke relay probe-surface` | tool_shaped | — |
| session_control.relay | `yoke relay serve-once` | tool_shaped | — |
| session_control.relay | `yoke relay serve` | tool_shaped | — |
| session_control.relay | `yoke relay status` | tool_shaped | — |
| session_control.relay | `yoke relay uninstall` | tool_shaped | — |
| source_authority.export | `yoke source-authority export` | tool_shaped | — |
| source_authority.quiesce | `yoke source-authority quiesce` | tool_shaped | — |
| status | `yoke status` | tool_shaped | — |
| tools.atlas | `python3 -m yoke_core.tools.atlas_render_docs check` | tool_shaped | — |
| tools.atlas | `python3 -m yoke_core.tools.atlas_render_docs render` | tool_shaped | — |
| tools.module_source_path | `python3 -m yoke_core.tools.module_source_path` | tool_shaped | — |
| tools.step_runners | `python3 -m yoke_core.tools.step_runners` | tool_shaped | — |
| tools.watch | `python3 -m yoke_core.tools.watch_advance` | tool_shaped | — |
| tools.watch | `python3 -m yoke_core.tools.watch_doctor` | tool_shaped | — |
| tools.watch | `python3 -m yoke_core.tools.watch_inventory` | tool_shaped | — |
| tools.watch | `python3 -m yoke_core.tools.watch_lifecycle` | tool_shaped | — |
| tools.watch | `python3 -m yoke_core.tools.watch_merge` | tool_shaped | — |
| tools.watch | `python3 -m yoke_core.tools.watch_pytest` | tool_shaped | — |
| tools.watch | `python3 -m yoke_core.tools.watch_session_offer` | tool_shaped | — |
| tools.watch | `python3 -m yoke_core.tools.watch_tail` | tool_shaped | — |
| tools.watch | `yoke watch tail` | tool_shaped | — |
| universe.export | `yoke universe export` | tool_shaped | — |
| universe.import | `yoke universe import` | tool_shaped | — |
| usher | `yoke usher reconcile-github` | tool_shaped | — |
| vps | `yoke vps start` | tool_shaped | — |
| vps | `yoke vps status` | tool_shaped | — |
| vps | `yoke vps stop` | tool_shaped | — |
| worktree | `python3 -m yoke_core.domain.worktree create` | tool_shaped | — |

### Human-only stranded work-claim release

When another session has ended but still owns a work claim, a human operator may release that exact claim through the retained operator-debug boundary:

```sh
python3 -m yoke_core.api.service_client claim-release \
 --item PREFIX-N --claim-id CLAIM_ID --reason "stranded session"
```

This is not an agent self-release recipe. It refuses hook contexts, records the reason on `OperatorClaimOverride`, and must only target a claim the operator has verified is stranded.

## 5. Pending handler-registration roster

_No pending handler-registration rows._

## 6. Teaching coverage

| path glob | count |
|---|---|
| .agents/skills/yoke/**/*.md | 135 |
| packages/yoke-core/src/yoke_core/domain/schema_api_context*.py | 32 |
| runtime/agents/*.md | 9 |
| runtime/harness/claude/agents/yoke-*.md | 8 |
| runtime/harness/codex/agents/yoke-*.toml | 8 |

Lint modules inventoried: **2** (0 reference the field-note footer; 0 carry denial text).

## 7. Field-note hotspots

Recent field-notes inspected: **50** (read surface: `agent_facing`).

| agent | recent count |
|---|---|
| codex | 45 |
| claude-code | 4 |
| cursor | 1 |

## 8. Contradictions

| id | status | surface | live truth |
|---|---|---|---|
| claims-work-holder-get-flag-vs-positional | resolved | yoke claims work holder-get | live `yoke claims work holder-get` accepts positional <YOK-N> |
| function-inventory-empty-registry-mismatch | resolved | docs/function-inventory.md | yoke_function_registry.list_entries() is non-empty |

## 9. Next-slice recommendation

_No outstanding follow-ups — the harness has nothing to recommend._

## 10. Curl floor — the envelope shape under every family

Every registered function id above accepts the same `FunctionCallRequest` envelope at the active env's `/v1/functions/call`. The `yoke` CLI is the default surface; curl is the operator floor when no CLI is installed:

```bash
API=https://app.stage.upyoke.com/api/orgs/upyoke-stage-1   # the active env's api_url
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
