# Getting started

## What is Yoke?

Yoke is a control plane for agentic engineering that gives humans and coding agents one shared source of truth for strategy, planning, implementation, testing, and deployment. You set the direction, and Yoke gets it done quickly and correctly.

<!-- yoke:visual shared-coordination -->


---

## Installation and setup

**Open Claude Code, Codex, or Cursor and say:** `install upyoke.com`

Your agent handles installation and guides you through setup, helping you make the right configuration choices.

Once setup is complete, your agent will launch the `/yoke onboard` skill. During onboarding, your agent reviews your project and existing work, helps you write your strategy and choose what to tackle first, and configures what's needed to test and deploy your project.

After `/yoke onboard`, your agent uses Yoke to organize work, staff it across your available machines and coding agents, and deliver it. It keeps you informed and brings key decisions to you.

[More on Installation and setup](guide/setup.install.md)

[More on Projects](guide/configuration.md)

[More on Packs](guide/configuration.packs.md)

[More on Agent guidance](guide/guidance.md)

[More on Steering and fleet control](guide/sessions.md)


---

## Hosting modes

A universe is the home for your Yoke projects, work records, and configuration. Each project brings together its software, goals, and work. You can keep several projects in one universe.

**Choose where your Universe lives during setup:**

<!-- yoke:visual hosting -->

You can move a universe between these options using export and import.

[More on Hosting modes](guide/setup.hosting.md)

[More on Self-hosting](guide/self-hosting.md)

[More on Universe portability, backup, and restore](guide/universe-portability.md)


---

## Team collaboration

You can use Yoke solo, including from multiple machines. In self-hosted and hosted modes, you can also invite everyone on your team to connect to the shared Universe. When multiple humans collaborate, Yoke is even more powerful, coordinating work in real time across all active users, machines, and harness sessions.

[More on Team collaboration](guide/access.collaboration.md)


---

## Yoke web dashboard

The web dashboard gives you a shared view of your Universe: projects, strategy, work items, agent sessions, QA, and deployments. Use it to follow progress, review evidence, and respond to questions and approvals.

### Local & self-hosted

Run in your Terminal:

`yoke ui up`

### Hosted

Private beta

[Log in at app.upyoke.com ↗](https://app.upyoke.com)

[More on Yoke web dashboard](guide/dashboard.md)


---

## Strategy docs

Strategy documents are markdown text stored in your Yoke Universe’s database that you and your agents can create, edit, and archive.

### Standing strategy docs

MISSION, VISION, LANDSCAPE, and MASTER-PLAN are “standing” docs that give humans and agents a shared understanding of the foundational context in which a project operates.

<!-- yoke:visual strategy-pyramid -->

### Working strategy docs

CURRENT-PLAN and other “working” strategy docs you create hold major initiatives, big slices of work, and ideas not yet filed as work items. Your agent files work items to track implementation and delivery, keeping the strategy doc updated with what’s filed, what remains, and current progress.

<!-- yoke:visual strategy-work -->

Work can be safely stopped and resumed anytime, from anywhere, without loss of any critical context.

[More on Strategy docs](guide/strategy.md)


---

## Steering and fleet control

Your coding agent uses Yoke to take a **STEERING** seat claim for one or more projects and working strategy docs. It files work items, staffs them on an available harness on your machine or another connected machine, and orchestrates delivery. You stay in the conversation to guide the work and make key decisions.

**STEERING** uses Yoke to launch parallel CLI sessions across all available machines and coding harnesses. Fleet messaging allows **STEERING** to communicate in real time with other sessions, and ensure coordinated execution and delivery.

<!-- yoke:visual fleet -->

[More on Steering and fleet control](guide/sessions.md)

[More on Yoke CLI and relay](guide/cli-relay.md)


---

## Workflows and work items

A workflow defines the stages work moves through, from an idea to delivery, and the checks required to move forward. Your agent chooses a workflow suited to the work, from a small change to a major initiative.

A work item is a piece of work following that workflow. It records what needs to be done, its plan and progress, and the evidence that it meets its goals.

<!-- yoke:visual workflow -->

Yoke ships with Dash, Issue, Epic, and Blitz workflows, each with different stages and gates, the checks required to advance. Execution posture settings control requirements such as verification, work isolation, and delivery. You can configure human approvals and default execution levels for stages, which determine the models and effort agents use.

[More on Workflows and work items](guide/work.md)


---

## The Frontier

The Frontier is the ever-evolving set of actionable, filed work items that Yoke can move through their workflows. Its dependency graph connects items with edges that explain what must happen before other work can start, merge, or finish. These relationships can span projects and reveal which work unlocks the most progress.

Yoke’s scheduler uses priorities, dependencies, workflow requirements, and existing work claims to determine what can advance next. Steering coordinates that work across your fleet, while `/yoke charge` lets you pick up work directly. The Frontier dashboard page shows what’s ready, active, or waiting, and why.

<!-- yoke:visual frontier -->

[More on The Frontier](guide/frontier.md)


---

## Execution instructions

Execution instructions are snippets of custom project-specific context that you and your agents configure through Yoke to reach the right agent at exactly the right time (following the principle of [progressive disclosure](https://www.anthropic.com/research/equipping-agents-for-the-real-world-with-agent-skills)). They can capture conventions, constraints, reminders, or procedures, scoped to selected projects, workflows, and workflow stages.

Manage instructions through your agent or the Workflows dashboard page. `/yoke onboard` will help you set them when you get started.

[More on Execution instructions](guide/execution-instructions.md)


---

## Quality assurance

With Yoke, you don't need to test everything yourself or engage in seemingly endless iteration cycles. Agents add appropriate QA check requirements to all work, specifying what must pass and when. Yoke has built-in QA methods ranging from deterministic to fully agentic, running locally and on external test machines.

QA cases are grouped into plans that can be easily copied, tweaked, and reused. Over time, your project becomes bulletproof. QA can run before merge, after merge, or after deployment, and against preview, ephemeral, dev, staging, or Production environments.

Yoke records each attempt’s results and evidence, tracks failures through correction and rechecking, and enforces required checks before work advances. Where human approval is configured, you can review the QA evidence e.g. screenshots and approve through the Yoke web dashboard.

<!-- yoke:visual qa -->

[More on Quality assurance](guide/qa.md)


---

## Deployments and releases

Work items that require deployment reach Done through a deployment run of their assigned flow. That flow defines the target environment and the steps required to complete delivery, including CI checks, GitHub Actions workflows, deployment commands, QA checks, and human approvals.

Environments represent where your software runs, such as preview, staging, and Production. A flow is the reusable definition; a run is one execution of it. A run can deliver several work items together, tracking each item’s required QA and delivery state.

Yoke records the release candidate, stage results, and evidence of what was deployed. You can follow progress in the web dashboard, respond to approvals, and see which work reached each environment. If a step fails, the run records the failure so your agent can diagnose it and recover.

<!-- yoke:visual deployment -->

[More on Deployments and releases](guide/delivery.md)


---

## Databases and migrations

Yoke can bring database changes into your project’s delivery process, with migration rehearsals, compatibility checks, and records of what was applied.

During `/yoke onboard`, your agent can register your project’s database and migration settings, or defer them until needed. Database access, a separate database for testing migrations, and integration with your deployment process require project-specific setup that your agent can help complete. Once configured, agents can rehearse database changes before release.

[More on Databases and migrations](guide/databases.md)


---

## Operations and troubleshooting

Yoke helps your agents find and fix problems. Doctor checks project health, while events, logs, and performance diagnostics help explain failures and slow operations. Agents can also diagnose connection problems and recover Yoke’s background services.

Ouroboros, Yoke’s learning loop, lets agents record problems as feedback, identify recurring issues, and turn those findings into improvements.

[More on Operations and troubleshooting](guide/operations.md)

[More on Command and technical reference](guide/reference/index.md)

<!-- yoke:contents -->
- [Installation and setup](guide/setup.install.md) — Guide installation, configuration, and project onboarding.
- [Hosting modes](guide/setup.hosting.md) — Help readers choose where their universe lives and understand how to move it later.
- [Self-hosting](guide/self-hosting.md) — Explain installing and operating a shared Yoke server on your own infrastructure.
- [Universe portability, backup, and restore](guide/universe-portability.md) — Explain moving and protecting a universe across installations and hosting modes.
- [Team collaboration](guide/access.collaboration.md) — Explain solo and team collaboration across machines and harness sessions in a shared Universe.
- [Strategy docs](guide/strategy.md) — Explain how direction becomes a plan and actionable work.
- [Yoke web dashboard](guide/dashboard.md) — Help people use the web dashboard to follow and coordinate their Yoke work.
- [The Frontier](guide/frontier.md) — Explain the Frontier as the boundary between strategy and filed work, how Yoke advances it, and how the dashboard presents it.
- [Workflows and work items](guide/work.md) — Explain how work is recorded and carried to completion.
- [Steering and fleet control](guide/sessions.md) — Explain who is working, how work is coordinated and when humans intervene.
- [Yoke CLI and relay](guide/cli-relay.md) — Explain the command-line interface and the machine relay that connects agent sessions to Yoke.
- [Agent guidance](guide/guidance.md) — Explain where instructions come from and when agents receive them.
- [Execution instructions](guide/execution-instructions.md) — Define reusable instructions for agents and control which work receives them and when.
- [Projects](guide/configuration.md) — Explain projects, their setup, structure, configuration, and integrations.
- [Packs](guide/configuration.packs.md) — Explain reusable setup and guidance and how projects adopt updates.
- [Quality assurance](guide/qa.md) — Explain how checks become trustworthy evidence and gate work.
- [Deployments and releases](guide/delivery.md) — Explain how code becomes a delivered change.
- [Databases and migrations](guide/databases.md) — Explain declared databases and safe changes to them.
- [Operations and troubleshooting](guide/operations.md) — Explain how to inspect health and recover without losing state.
- [Command and technical reference](guide/reference/index.md) — Give agents and advanced readers precise contracts without crowding human overviews.
<!-- /yoke:contents -->
