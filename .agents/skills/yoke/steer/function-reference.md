# /yoke steer — registered operation authority

Read this when you need a steering operation's function id or exact
adapter shape. It is a lookup, not a phase step.

| Function id | CLI adapter |
|---|---|
| `claims.steering.acquire` | `yoke claims steering acquire --project P [--doc SLUG \| --plan-doc SLUG] [--reason TEXT]` |
| `claims.steering.release` | `yoke claims steering release CLAIM_ID --reason TEXT` |
| `claims.steering.list` | `yoke claims steering list --project P --active-only` |
| `strategy.doc.get` | `yoke strategy doc get SLUG [--project P]` |
| `strategy.doc.create` | `yoke strategy doc create SLUG --stdin [--project P]` |
| `strategy.execution.link` | `yoke strategy execution link ITEM --slug SLUG --project P` |
| `items.create` (Dash) | `yoke dash "TITLE" "INSTRUCTION" --strategy-doc SLUG --execution-instructions-considered` |
| `items.detail.get` | `yoke items detail get PREFIX-N --json` |
| `workflows.item.get` | `yoke workflows item get PREFIX-N --json` |
| `claims.work.acquire` | `yoke claims work acquire --item PREFIX-N --reason TEXT` |
| `claims.work.release` | `yoke claims work release (--item PREFIX-N \| --all-mine) --reason TEXT` |
| `claims.work.holder_list` | `yoke claims work holder-list --session-id-filter S --json` |
| `claims.coordination_claim.list` | `yoke claims coordination-claim list --session-id S --active-only --json` |
| `claims.coordination_claim.release` | `yoke claims coordination-claim release (--project P --key K \| --claim-id N) --reason TEXT` |
| `steering.report.get` | `yoke steering report get [--project P]` |
| `session_control.launch.preview` | `yoke session-control launch preview --project P --surface S [--machine M] [--model M] [--reasoning-effort E] [--context-window N] --json` |
| `session_control.launch.create` | `yoke session-control launch create --project P --surface S [--item PREFIX-N] --idempotency-key K [--stdin] [--raw-instructions] [--machine M] [--model M] [--reasoning-effort E] [--context-window N]` |

`--machine` accepts the registered name the fleet report prints, or a machine id from `yoke machine list`. An unresolvable value is `machine_unresolved`, not an absent relay.
| `session_control.launch.get` | `yoke session-control launch get LAUNCH-ID --json` |
| `session_control.launch.list` | `yoke session-control launch list --project P` |
| `session_control.launch.reconcile` | `yoke session-control launch reconcile LAUNCH-ID --json` |
| `session_control.launch.retry` | `yoke session-control launch retry LAUNCH-ID --json` |
| `session_control.surface_policy.disable` | `yoke session-control surface-policy disable --project P --machine M --surface S --reason TEXT` |
| `session_control.surface_policy.enable` | `yoke session-control surface-policy enable --project P --machine M --surface S` |
| `session_control.surface_policy.list` | `yoke session-control surface-policy list [--machine M]` |
| `session_control.session.terminate` | `yoke sessions terminate SESSION-ID --reason R` |
| `session_control.message.send` | `yoke say --item PREFIX-N --stdin` (workers reply with `yoke say --steering`) |
| `session_control.message.acknowledge` | `yoke messages acknowledge MESSAGE-ID` |
| `charge.schedule` | `yoke charge schedule --project P` |
| `deployment_runs.create` | `yoke --env <cp> deployment-runs create PROJECT FLOW ...`; paired `*-db-admin` only for a serving-API self-deploy |

Do not invoke `/yoke feed`. Feed and steer are unrelated.
