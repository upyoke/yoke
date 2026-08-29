# Command resolution

The agent-facing `yoke` entrypoint resolves taught command spellings through
the function registry, client-local tool registry, or an explicit navigation
route. Navigation routes print the real commands for an ambiguous or
historically intuitive group; they do not dispatch a guessed mutation.

| Reached-for spelling | Current resolution |
|---|---|
| `yoke deployment-flows list` | Registered `deployment_flows.list` read. |
| `yoke deployment-runs find-by-item` | Registered `deployment_runs.find_by_item` read. |
| `yoke deployment-runs failure-trace` | Registered terminal-cause and dispatch-chain read. |
| `yoke deployment-runs stages` | Registered `deployment_runs.stages` progress read. |
| `yoke deployments` | Navigation to the deployment-flow and deployment-run groups. |
| `yoke workflows version list` | Registered `workflows.version.list` inventory read. |
| `yoke worktrees` | Navigation to the registered `item-worktrees` group. |
| `yoke simulate` | Guidance to the `/yoke simulate` harness skill; simulation is not a terminal operation. |
| `yoke env list` | Client-local inventory of configured connection environments. |
| `yoke qa review` | Navigation to the typed `yoke qa plan review-submit` surface. |
| `yoke sessions end-if-empty` | Registered self-scoped, claim-aware session closeout. |
| `yoke claims path amend` | Registered `claims.path.amend` mutation. |
| `yoke github actions wait` | Space-separated namespace route to the registered GitHub Actions wait adapter. |
| `yoke source` | Navigation to the `source-authority` group. |
| `yoke doctor` | Bare-group help for the registered doctor commands. |
| `yoke github actions get` | Navigation to the registered GitHub Actions reads so the caller selects the intended subject. |
| `yoke sessions reclaim-stale --confirm` | Registered guarded stale-session reclamation; the lower-level cleanup commands are removed. |

`HC-atlas-integrity` extracts command spellings from live skills, agent
bodies, packets, command help, recovery/denial text, and command-reference
documentation. Any taught `yoke` spelling that does not resolve fails the
health check, and the full test suite exercises that check before merge.
