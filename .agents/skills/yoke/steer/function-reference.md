# Steer — registered operation lookup

Read selected command help for exact envelope/limits; strategy write depth is
.yoke/docs/reference/db-reference/functions-project-configuration.md. This is
lookup, not a phase. No feed. All launches go through Yoke; --machine takes
registered name/id, machine_unresolved is not absent relay.

| Function id | CLI read/write surface |
|---|---|
| claims.steering.acquire | yoke claims steering acquire --project P --doc SLUG --reason TEXT (use --plan-doc for project coverage) |
| claims.steering.list | yoke claims steering list --project P --active-only |
| claims.steering.release | yoke claims steering release CLAIM_ID --reason TEXT |
| strategy.doc.get | yoke strategy doc get SLUG --project P |
| strategy.doc.create | yoke strategy doc create SLUG --summary TEXT --state draft --stdin --project P |
| strategy.execution.link | yoke strategy execution link ITEM --slug SLUG --project P |
| items.create | yoke dash TITLE INSTRUCTION --strategy-doc SLUG --execution-instructions-considered |
| items.detail.get | yoke items detail get PREFIX-N --json (use --include '' for index-only) |
| workflows.item.get | yoke workflows item get PREFIX-N --json |
| claims.work.acquire | yoke claims work acquire --item PREFIX-N --reason TEXT |
| claims.work.release | yoke claims work release --item PREFIX-N --reason TEXT (or --all-mine) |
| claims.work.holder_list | yoke claims work holder-list --session-id-filter SESSION-ID --json |
| claims.coordination_claim.list | yoke claims coordination-claim list --session-id SESSION-ID --active-only --json |
| claims.coordination_claim.release | yoke claims coordination-claim release --project P --key KEY --reason TEXT |
| steering.report.get | yoke steering report get (all held scopes) |
| session_control.launch.preview | yoke session-control launch preview --project P --level LEVEL --json |
| session_control.launch.create | yoke session-control launch create --project P --item PREFIX-N --idempotency-key K |
| session_control.launch.get | yoke session-control launch get LAUNCH-ID --json |
| session_control.launch.list | yoke session-control launch list --project P |
| session_control.launch.reconcile | yoke session-control launch reconcile LAUNCH-ID --json |
| session_control.launch.retry | yoke session-control launch retry LAUNCH-ID --json |
| session_control.surface_policy.disable | yoke session-control surface-policy disable --project P --machine M --surface S --reason TEXT |
| session_control.surface_policy.enable | yoke session-control surface-policy enable --project P --machine M --surface S |
| session_control.surface_policy.list | yoke session-control surface-policy list --machine M |
| session_control.session.terminate | yoke sessions terminate SESSION-ID --reason R |
| session_control.session.wake | yoke session-control session wake --item PREFIX-N --json |
| session_control.evidence.get | yoke session-control evidence get --session SESSION-ID |
| session_control.message.send | yoke say --item PREFIX-N --stdin (peer copy --steering; workers report --steering) |
| session_control.message.acknowledge | yoke messages acknowledge MESSAGE-ID |
| charge.schedule | yoke charge schedule --project P |
| deployment_runs.create | yoke --env CONTROL_PLANE deployment-runs create PROJECT FLOW --idempotency-key KEY |

Judge the leg before every item launch: mechanical/small bugs/docs/cleanup →
`--level JUNIOR`; trivial specified → `--level INTERN`; real design/implementation
→ stage level (omit `--level`); very complex → PRINCIPAL. Read
[model-selection.md](model-selection.md). Preview must be launchable; itembound
--level plus optional level-reason records every-stage override and item_level
receipt, refuses item_level_not_recordable on incompatible pin. Itemless
--level/raw-instructions/--stdin requires nonempty body and places only that
launch. Exact operator --surface/model/effort/context excludes level.
level_no_capacity names actual options; launch_replay_finished creates nothing,
so a deliberate successor uses fresh key. --machine optionally narrows.
See worker-launch for full mandate/receipt/reconcile/deadline and substantive
peer requester+steering routing; source-dev-delivery owns self-deploy authority.
