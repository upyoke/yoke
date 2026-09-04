# Delivery

Workbench **Delivery** has four destinations:

| Destination | Meaning |
|---|---|
| **Runs** | Each execution of a flow against an environment |
| **Environments** | Deploy targets |
| **Flows** | Pipeline definitions runs execute |
| **Databases** | Declared DB models, posture, apply records — see [databases-and-migrations.md](databases-and-migrations.md) |

## Item-bound delivery

`/yoke usher` and `yoke deployment-runs start-for-item` bind implemented work
to a run, execute the pipeline, and move members toward done. Flow id ≠ run
id (`run-YYYYMMDD-NNN`).

## Hosting

There is no separate Hosting destination. Hosting shows up as:

- Packs (production-deploy, runners, environment infra, …)
- `/yoke onboard` gated first deploy
- Environment settings (projected scalar reads only — never dump whole
  settings documents)

## Disable vs delete

Disable a flow definition to stop new assignments while retaining history.
Definitions referenced by runs are immutable.
