# Delivery

Workbench delivery has three destinations, and **Deployments** carries two
tabs because a flow definition and a run of it are two readings of one
subject:

| Destination | Meaning |
|---|---|
| **Deployments → Flows** | Pipeline definitions runs execute. Read-only here: definitions are authored by command. |
| **Deployments → Runs** | Each execution of a flow against an environment. Opening a row opens that run. |
| **Environments** | Deploy targets |
| **Databases** | Declared DB models, posture, apply records — see [databases-and-migrations.md](databases-and-migrations.md) |

Flows is the tab Deployments opens on. Runs live at `#/deployments/runs`, and
one run at `#/deployments/runs/<run id>`.

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
