# /yoke steer — registered operation authority

Strategy document writes: create with `--summary TEXT` and `--state TEXT`, one non-empty plain-text line each. Summary is bounded by `SUMMARY_MAX_CHARS` and State by `STATE_MAX_CHARS` from `yoke_contracts.project_contract.strategy_doc_fields`; the command’s `--help` prints both current limits. Replace, section-replace, and ingest keep exactly one Summary and one State heading, with the current `(N chars max)` suffix; legacy headings normalize on save. State is free text. Revision restore accepts optional `--summary` / `--state` to repair an invalid old revision; coordination append cannot target these fields. Read the write command’s `--help` before acting.

Read this when you need a steering operation's function id or exact
adapter shape. It is a lookup, not a phase step.

| Function id | CLI adapter |
|---|---|
| `claims.steering.acquire` | `yoke claims steering acquire --project P [--doc SLUG \| --plan-doc SLUG] [--reason TEXT]` |
| `claims.steering.release` | `yoke claims steering release CLAIM_ID --reason TEXT` |
| `claims.steering.list` | `yoke claims steering list --project P --active-only` |
| `strategy.doc.get` | `yoke strategy doc get SLUG [--project P]` |
| `strategy.doc.create` | `yoke strategy doc create SLUG --summary TEXT --state TEXT --stdin [--project P]` |
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
| `session_control.launch.create` | Preview first. Item-bound: `yoke session-control launch create --project P --surface S --item PREFIX-N --idempotency-key K`. Itemless: `yoke session-control launch create --project P --surface S --raw-instructions --stdin --idempotency-key K` with a nonempty stdin body. Both accept `[--machine M] [--model M] [--reasoning-effort E] [--context-window N]`. A replay whose session ended refuses as `launch_replay_finished`: no new worker started; relaunch with a new key. |

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
| `deployment_runs.create` | `yoke --env <cp> deployment-runs create PROJECT FLOW --idempotency-key KEY ...`; paired `*-db-admin` only for a serving-API self-deploy |

`--machine` accepts the registered name the fleet report prints, or a machine id from `yoke machine list`. An unresolvable value is `machine_unresolved`, not an absent relay.

Do not invoke `/yoke feed`. Feed and steer are unrelated.
