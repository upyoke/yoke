# Runtime Function Catalog

Read [envelope and authority](functions.md) first. `none` means no dispatcher work-claim check; handler permissions still apply. Read command help for the live payload and serving floor.

## Registered functions

| Function id | Claim policy |
|---|---|
| `actors.role.set` | `none` |
| `actors.roster` | `none` |
| `actors.state.set` | `none` |
| `agents.render.check` | `none` |
| `agents.render.run` | `none` |
| `agents.render_relationships.record` | `none` |
| `auth.set.run` | `none` |
| `board.data.get` | `none` |
| `board.rebuild.run` | `none` |
| `db.read.run` | `none` |
| `deployment_flows.create` | `none` |
| `deployment_flows.describe` | `none` |
| `deployment_flows.get` | `none` |
| `deployment_flows.list` | `none` |
| `deployment_flows.reorder` | `none` |
| `deployment_flows.set_status` | `none` |
| `deployment_flows.stages` | `none` |
| `deployment_flows.update` | `none` |
| `deployment_flows.update_stages` | `none` |
| `deployment_flows.validate` | `none` |
| `deployment_flows.version` | `none` |
| `deployment_item_stamp.record` | `none` |
| `deployment_runs.add_item` | `none` |
| `deployment_runs.approve` | `none` |
| `deployment_runs.carried_work.repair` | `none` |
| `deployment_runs.continue_for_item` | `item` |
| `deployment_runs.create` | `none` |
| `deployment_runs.driver.for_capture` | `none` |
| `deployment_runs.execution.attach_driver` | `none` |
| `deployment_runs.execution.bound_sources_current` | `none` |
| `deployment_runs.execution.containment_basis` | `none` |
| `deployment_runs.execution.context` | `none` |
| `deployment_runs.execution.ephemeral_qa_ready` | `none` |
| `deployment_runs.execution.qa_pending` | `none` |
| `deployment_runs.execution.qa_record` | `none` |
| `deployment_runs.execution.qa_seed` | `none` |
| `deployment_runs.execution.release_driver` | `none` |
| `deployment_runs.execution.stage_receipt_allocate` | `none` |
| `deployment_runs.execution.stage_receipt_complete` | `none` |
| `deployment_runs.execution.stage_receipt_latest` | `none` |
| `deployment_runs.execution.update` | `none` |
| `deployment_runs.failure_trace` | `none` |
| `deployment_runs.find_by_item` | `none` |
| `deployment_runs.get` | `none` |
| `deployment_runs.list` | `none` |
| `deployment_runs.project_snapshot` | `none` |
| `deployment_runs.qa_stage.dispatch` | `none` |
| `deployment_runs.qa_stage.resume_refusals` | `none` |
| `deployment_runs.release_output.record` | `none` |
| `deployment_runs.remove_item` | `none` |
| `deployment_runs.resolve_target` | `none` |
| `deployment_runs.stage_approval.evaluate` | `none` |
| `deployment_runs.stages` | `none` |
| `deployment_runs.start_for_item` | `item` |
| `deployment_runs.terminalize` | `none` |
| `deployment_runs.update` | `none` |
| `deployment_runs.validate_composition` | `none` |
| `doctor.last_run.get` | `none` |
| `doctor.run.run` | `none` |
| `ephemeral_env.create` | `none` |
| `ephemeral_env.get` | `none` |
| `ephemeral_env.update` | `none` |
| `events.anomalies.run` | `none` |
| `events.count.run` | `none` |
| `events.emit` | `none` |
| `events.performance.aggregate` | `none` |
| `events.performance.detail` | `none` |
| `events.query.run` | `none` |
| `events.tail.run` | `none` |
| `github.branch.head` | `none` |
| `github.merge_queue.apply` | `none` |
| `github.merge_queue.hold` | `item` |
| `github.merge_queue.readiness` | `none` |
| `github.pr.create` | `none` |
| `github.release.create_next_tag` | `none` |
| `github_actions.check_ci` | `none` |
| `github_actions.commit_runs.list` | `none` |
| `github_actions.dispatch_tag.ensure` | `none` |
| `github_actions.failed_log` | `none` |
| `github_actions.run.jobs_count` | `none` |
| `github_actions.runners.status` | `none` |
| `github_actions.secret.delete` | `none` |
| `github_actions.secret.set` | `none` |
| `github_actions.variable.delete` | `none` |
| `github_actions.variable.get` | `none` |
| `github_actions.variable.set` | `none` |
| `github_actions.wait_run` | `none` |
| `github_actions.workflow.dispatch` | `none` |
| `github_actions.workflow.dispatch_once` | `none` |
| `github_actions.workflow.find_run` | `none` |
| `harness.machine_report.upsert` | `none` |
| `hook.evaluate.run` | `none` |
| `identity.invite.create` | `none` |
| `identity.invite.list` | `none` |
| `identity.invite.revoke` | `none` |
| `identity.link.set` | `none` |
| `inbox.list` | `none` |
| `lint.config.show` | `none` |
| `machine.detail` | `none` |
| `machine.list` | `none` |
| `machine.register` | `none` |
| `machine.retire` | `none` |
| `machine.settings.get` | `none` |
| `machine.settings.set` | `none` |
| `machine.show` | `none` |
| `machine_approval.lifecycle.apply` | `none` |
| `machine_authorization.get` | `none` |
| `machine_authorization.resolve` | `none` |
| `migration.content_identity.verify` | `none` |
| `models.diff.run` | `none` |
| `models.get.run` | `none` |
| `models.level_proposal.run` | `none` |
| `models.lookup.run` | `none` |
| `models.publish.run` | `none` |
| `models.restore.run` | `none` |
| `models.revisions.run` | `none` |
| `models.validate.run` | `none` |
| `organizations.create` | `none` |
| `organizations.domain.set` | `none` |
| `organizations.get` | `none` |
| `organizations.settings.catalog` | `none` |
| `organizations.settings.get` | `none` |
| `organizations.settings.merge` | `none` |
| `ouroboros.entry.get` | `none` |
| `ouroboros.entry.insert` | `none` |
| `ouroboros.entry.list` | `none` |
| `ouroboros.entry.mark_archived` | `none` |
| `ouroboros.entry.mark_reviewed` | `none` |
| `ouroboros.field_note.append` | `none` |
| `ouroboros.field_note.get` | `none` |
| `ouroboros.field_note.list` | `none` |
| `ouroboros.field_note.promote` | `none` |
| `overview.activation.get` | `none` |
| `overview.module.dismiss` | `none` |
| `overview.module.restore` | `none` |
| `overview.vitals.get` | `none` |
| `packets.budget.get` | `none` |
| `packets.check.run` | `none` |
| `packets.render.run` | `none` |
| `packets.startup_delivery.get` | `none` |
| `profile.get` | `none` |
| `profile.onboarding.reset` | `none` |
| `profile.preference.set` | `none` |
| `profile.token.create` | `none` |
| `profile.token.revoke` | `none` |
| `scratch.dispatch_inputs` | `none` |
| `session_ci_wait.record` | `none` |
| `session_ci_wait.resolve` | `none` |
| `session_control.evidence.get` | `none` |
| `session_control.keepalive.hold` | `none` |
| `session_control.keepalive.release` | `none` |
| `session_control.launch.cancel` | `none` |
| `session_control.launch.create` | `none` |
| `session_control.launch.get` | `none` |
| `session_control.launch.list` | `none` |
| `session_control.launch.preview` | `none` |
| `session_control.launch.reconcile` | `none` |
| `session_control.launch.retry` | `none` |
| `session_control.message.acknowledge` | `none` |
| `session_control.message.cancel` | `none` |
| `session_control.message.get` | `none` |
| `session_control.message.lease` | `none` |
| `session_control.message.list` | `none` |
| `session_control.message.preview` | `none` |
| `session_control.message.send` | `none` |
| `session_control.qualification.open` | `steering` |
| `session_control.relay.claim` | `none` |
| `session_control.relay.idle_hosts` | `none` |
| `session_control.relay.list` | `none` |
| `session_control.relay.liveness` | `none` |
| `session_control.relay.report` | `none` |
| `session_control.relay.turn_end` | `none` |
| `session_control.session.terminate` | `none` |
| `session_control.session.wake` | `none` |
| `session_control.surface_policy.disable` | `none` |
| `session_control.surface_policy.enable` | `none` |
| `session_control.surface_policy.list` | `none` |
| `sessions.begin` | `none` |
| `sessions.checkpoint` | `none` |
| `sessions.checkpoint_read` | `none` |
| `sessions.end_if_empty` | `none` |
| `sessions.hook_overhead` | `none` |
| `sessions.identity` | `none` |
| `sessions.list` | `none` |
| `sessions.reclaim_stale` | `none` |
| `sessions.steering_groups.list` | `none` |
| `sessions.touch` | `none` |
| `steering.report.get` | `none` |
| `ui_preferences.nav_group.list` | `none` |
| `ui_preferences.nav_group.set` | `none` |
| `ui_preferences.screen_selection.list` | `none` |
| `ui_preferences.screen_selection.set` | `none` |
| `ui_preferences.search_history.list` | `none` |
| `ui_preferences.search_history.record` | `none` |

## Runtime authority and output

The board data read is the server half of explicit board rebuilding: it returns
the recorded DB plan and the checkout project's VISION identity; the client
renders/writes markdown with local inputs. Nothing rebuilds automatically.
Packet budget reports configured line usage/headroom per role and in aggregate;
character counts measure usage and are not enforced limits. Agent render/check
compose native adapters from the same canonical sources.

Doctor requires project context and exactly one scope: quick, full or named
checks. Missing context/scope and unknown checks refuse by name. Runtime is the
executing destination; applicable checks derive from project/capability/tree
facts. N/A carries its reason and is never counted green or dropped. Events are
diagnostic telemetry. Session CI wait records the exact session/run once and
resolves that pair after its watcher receives the verdict; supersession clears
abandoned waits without manufacturing a test result.

Deployment definitions retain history and immutable referenced versions. Run
creation/execution requires the project deployment hold, registered authority,
exact lineage and composition proof; a run id is not a flow id. A driver owns
its attachment and continuation. Read [deployment contracts](events-and-deployments.md)
before operating. Ephemeral-environment updates authorize the owning project;
terminal status retains stopped-at behavior and invalid fields refuse.

Sessions, launch/wake/message and machine operations use manifest capabilities,
authenticated outer delivery and exact bound identity. Message bodies grant no
authority. Read [fleet policy](fleet-policy.md) before cross-machine operations.
Personal machine authorization resolves approve/deny under signed-in ownership;
hosted decisions belong to the authorized org admin. Profile writes act only on
the caller's own identity/preferences/tokens; raw new token appears once.
Machine-bound credentials are retired through their machine, never arbitrary
profile token removal.

## Actors and org roles

Actors functions use global targets and the bound actor. Roster returns kinds,
states, org/project roles, linked email, live-key metadata, current actor and
org-admin management capability. State changes require org admin; disabling
revokes keys/browser sessions. Role set targets actor id or uniquely linked
member email and replaces a person's one org role, returning old/new roles and
changed state. Sign-in once resolves unlinked email; ambiguous email needs id.
System-actor retirement also requires `--confirm-system-retirement`; inspect
the actor and credential owner before explicitly confirming that retirement.

A person has exactly one role from
`yoke_core.domain.actor_role.HUMAN_ORG_ROLES`: admin, operator or viewer.
Operator works across the org's projects. Machine-only roles are deployment_ci,
hosted_service, infrastructure_ci and migration_verification_ci; system roles
accumulate. Every grant uses the same person-role validator, including invites,
sign-in, bootstrap and local seeding. Invite-role validation precedes creation,
linking or acceptance; refusal names revoke recovery.

```sh
yoke actors state set <actor-id> --disable
yoke actors role set <actor-id> --role ROLE
```

| Refusal | Recovery |
|---|---|
| last_admin | Make another active person admin before demoting the last. |
| machine_only_role / role_not_assignable | Choose a supported person role. |
| actor_not_human | System roles come from their provisioning credential. |
| actor_not_found | Refresh roster. |
| member_not_linked | Member signs in, or use actor id. |
| member_ambiguous | Use exact actor id. |
| permission_denied | Caller must have org-admin authority. |

Overview activation reads/latches universe setup facts; hiding removes a module
until the caller explicitly resets onboarding preferences. Per-machine connect
facts include approval/hook health, and onboarding facts retain live outcomes,
next action/blocker and superseding deployment. Latching never rewrites current
evidence. Model/auth/identity/migration runtime operations keep their own
permission and serving-floor contracts; command help names the reachable repair.
