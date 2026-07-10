> Orientation doc: describes the intended operating model and may lead the current implementation.

# Yoke

### Yoke runs companies. Software delivery is the first capability.

Yoke turns ideas into shipped, deployed, verified code through a disciplined pipeline. The main path is frontier-based item flow: shepherd items to readiness, advance them through implementation, and usher them to production. Seven specialized subagents and three orchestration skills do the work. Postgres holds control-plane state. Git worktrees give you conflict-free parallelism. You make every decision that matters. The AI executes.

Longer term, Yoke becomes a central clearinghouse for company operations — receiving work from many channels, classifying it, routing it into the right lane, and maintaining richly linked facts about intent, participants, state transitions, and outcomes.

---

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Table of Contents

- [Master Flowchart](#master-flowchart)
- [Quick Start](#quick-start)
- [Core Concepts](#core-concepts)
- [Item Lifecycle](#item-lifecycle)
- [Command Reference](#command-reference)
- [Architecture](#architecture)
- [Ouroboros — Self-Improvement](#ouroboros--self-improvement)
- [Multi-Project Support](#multi-project-support)
- [FAQ](#faq)
- [Contributing](#contributing)
- [License](#license)

---

## Master Flowchart

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  IDEA CAPTURE                                                                       │
│  /yoke idea "title"  →  YOK-N, status=idea  →  SQL + GitHub issue                │
└──────────────────────────────────────┬──────────────────────────────────────────────┘
                                       │
                                       ▼
                    ┌──────────────────────────────────────────────────────────────────┐
                    │  OPTIONAL SHEPHERD                                               │
                    │  PM → Boss → [Designer] → [Architect → Simulator] → Boss        │
                    │  Use when more structure or gatekeeping is worth it              │
                    └──────────────────────────┬───────────────────────────────────────┘
                                               │
                                               ▼
        ┌──────────────────────────────────────────────────────────────────────┐
        │ ITEM FLOW                                                            │
        │ /yoke advance YOK-N implementing                                     │
        │ work in worktree                                                     │
        │ /yoke conduct YOK-N if needed                                      │
        │ → item reaches implemented                                           │
        └──────────────────────────────┬───────────────────────────────────────┘
                                       │
                           operator can pause at any point and ask the agent:
                     "what can run next in parallel and what should merge first?"
                                                         │
                                                         ▼
                    ┌────────────────────────────────────────────────────────────────┐
                    │  USHER (/yoke usher)                                         │
                    │  merge → deploy → verify → done                                │
                    │  halt states: needs-capability / awaiting-approval             │
                    └──────────────────────────────┬─────────────────────────────────┘
                                                   │
                                                   ▼
                                      ┌──────────────────────────┐
                                      │          DONE            │
                                      │ deploy complete / logged │
                                      └──────────────────────────┘
```

---

## Quick Start

> New to Yoke's supported agent hosts? See
> [docs/local-setup.md](docs/local-setup.md#agent-hosts) first, then come
> back here.

**Fresh machine? Install the product CLI first.**

The only prerequisites are a shell, `curl`, and `uv`. The public installer
ensures `uv` is present (installing it on consent when missing), then installs
`yoke` with a single uv invocation. uv provisions a managed Python, resolves
dependencies, and links `yoke` onto PATH — you are never asked to bring your
own Python.

```bash
curl -fsSL https://api.upyoke.com/install | bash
yoke onboard
yoke status
```

The installer auto-launches `yoke onboard` when interactive. The manual,
advanced equivalent of the install step is a direct uv invocation using one
resolved channel version for every Yoke product package:

```bash
uv tool install yoke-cli==<version> --python '>=3.10' --reinstall --with yoke-contracts==<version> --with yoke-harness==<version> --with yoke-core==<version> --index-url https://api.upyoke.com/simple/ --extra-index-url https://pypi.org/simple/
```

To upgrade later, rerun the curl installer, or rerun the same lockstep uv
command with the new channel version.

**Prefer everything on your own machine?** Local mode is free and needs no
signup or token: `yoke init --local` fetches an embedded Postgres, births a
complete machine-local universe under `~/.yoke/`, and points the machine
config at it. When you want to leave or graduate to another deployment
mode, `yoke universe export` dumps the whole universe to one portable
`pg_restore`-compatible artifact. See
[docs/local-setup.md](docs/local-setup.md) ("Local Mode").

Optionally connect the Yoke GitHub App for product commands that need to
inspect or write GitHub from this machine:

```bash
yoke github connect
yoke github status
```

`yoke onboard` is a full-screen wizard: a fixed header and stepper stay on
screen — Install/PATH, Account, GitHub, Project, Review — while you move
through the steps with the arrow keys. The Account step opens on a
deployment-destination picker (this machine / a team server / upyoke.com);
only the sign-in lane changes with the answer — "This machine" births the
free local universe with no account, a team server collects your server URL
plus a token, upyoke.com signs in to the hosted platform. The Project step
lets you pick the project source — just this machine, create a checkout,
clone a remote, import an existing remote, onboard a local checkout, or the
explicit source-dev/admin opt-in — and the wizard previews every persistent
write before applying. Pass `--yes` for a silent, non-interactive apply;
`--local` and `--connect URL` mirror the picker without the TUI.

The same project modes are also available as standalone product commands when
you want to script a single mode:

```bash
# New repo
yoke project create ~/work/my-app \
  --slug my-app --name "My App" --github-repo owner/my-app \
  --default-branch main --public-item-prefix APP \
  --github-adoption backlog-only \
  --config ~/.yoke/config.json --yes

# Existing remote
yoke project import git@github.com:owner/my-app.git ~/work/my-app \
  --slug my-app --name "My App" --github-repo owner/my-app \
  --default-branch main --public-item-prefix APP \
  --github-adoption backlog-only --config ~/.yoke/config.json --yes

# Existing local checkout
yoke onboard project ~/work/my-app \
  --slug my-app --name "My App" --github-repo owner/my-app \
  --default-branch main --public-item-prefix APP \
  --github-adoption backlog-only --config ~/.yoke/config.json --yes
```

`git` is needed only when a project mode creates, clones, imports, or registers
a checkout — machine-only onboarding needs no git.

If the project already exists in the Yoke env and only needs the local
operating layer, install it directly:

```bash
yoke project install ~/work/my-app \
  --project-id <project-id> --config ~/.yoke/config.json
```

Capture the project command's JSON install report, initialize the durable
onboarding checklist, then hand the repo to the harness-side adoption skill:

```bash
yoke onboard checklist init \
  --config ~/.yoke/config.json \
  --checkout ~/work/my-app --project-id <project-id> --json
```

Open the installed project in a supported harness and run:

```text
/yoke onboard-project --project-root ~/work/my-app --run-id <run-id>
```

Yoke source developers follow the same product install first. After the
Yoke checkout is project-installed, run the explicit source-dev setup:

```bash
yoke project install ~/yoke \
  --project-id <yoke-project-id> --config ~/.yoke/config.json
yoke dev setup ~/yoke \
  --config ~/.yoke/config.json --set-active-env
```

```bash
# Direct item flow (most common)
/yoke idea "fix login bug"
/yoke shepherd YOK-N                # Optional
/yoke advance YOK-N implementing     # Creates worktree
# (work in worktree)
/yoke conduct YOK-N                 # Only if needed to finish pre-merge work
/yoke usher YOK-N
```

Yoke supports an operator-driven planning loop: ask the agent to inspect current state, what landed, what is unblocked, what can run next in parallel, and what order to merge in, then decide in real time how to proceed.

---

## Core Concepts

### Item Types

| Type      | What it is                                    | Decomposes into tasks?                     |
| --------- | --------------------------------------------- | ------------------------------------------ |
| **Issue** | Single unit of work (bug, feature, config)    | No                                         |
| **Epic**  | Large work that the Architect decomposes      | Yes — into tasks with worktree assignments |
| **Task**  | Sub-item of an epic, created by the Architect | No                                         |

The rendered item body is the spec view — no separate PRD files. `items get YOK-N body` renders the authoritative spec from structured fields. One artifact, one lifecycle, one source of truth.

### The Seven Agents

**Workers** — produce artifacts in isolated subagent sessions:

| Agent                | Role                                                                          | Key Constraint                  |
| -------------------- | ----------------------------------------------------------------------------- | ------------------------------- |
| **Product Manager**  | Writes specs and acceptance criteria into item bodies                         | Read-only                       |
| **Product Designer** | UX spec from item body + existing UI patterns (optional)                      | Read-only                       |
| **Architect**        | Decomposes item body → epic plan + tasks + worktree assignments               | Read-only + Bash                |
| **Engineer**         | Implements task: code + tests + docs, commits incrementally                   | Full tools, `bypassPermissions` |
| **Tester**           | Validates against acceptance criteria, runs tests                             | **Cannot modify code**          |
| **Simulator**        | Traces cross-task paths for integration gaps                                  | Read-only                       |

**Evaluator:** **Boss** — per-artifact quality gate (simulated PM/Architect/Engineer debate → READY / NOT READY / CAVEATS). Caveats flow downstream as explicit constraints to the next worker.

> **Shepherd, Conduct, and Usher** are orchestration skills (`/yoke shepherd`, `/yoke conduct`, `/yoke usher`), not agents. They run inline in the main session.

---

## Item Lifecycle

At the operator level:

- **Intake:** `idea`
- **Definition:** optional shepherding until `refined-idea` (issues) or `planned` (epics)
- **Execution:** `implementing` through engineer / tester / simulator checks
- **Delivery gate:** `implemented` — pre-deploy work complete, ready for usher
- **Delivery:** usher drives deploy / verify until `done`

**`done`** means the delivery workflow completed with evidence — not just "code landed."

### Deployment flows

Every item has a **deployment flow** selected during shepherding. Examples:

| Flow | When used | Stages after `implemented` |
|------|-----------|---------------------------|
| `internal` | Scripts, docs, config | complete |
| `buzz-prod-hotfix` | Urgent prod fix | prod-deploy → smoke → complete |
| `buzz-prod-release` | Standard feature | prod-deploy → smoke → complete |

Stage executor types: `auto`, `health-check`, `script`, `human-approval`, `github-actions-workflow`. All stage failures halt for v1; re-run `/yoke usher YOK-N` to resume.

---

## Command Reference

### Primary entry points

| Command                         | Purpose                                                                                  |
| ------------------------------- | ---------------------------------------------------------------------------------------- |
| `/yoke idea {title}`          | Create a backlog item.                                                                   |
| `/yoke conduct YOK-N`          | Execute: sync → engineer → test → simulate → merge.                                     |
| `/yoke shepherd YOK-N`        | Advance: idea → refined-idea (or planned for epics).                                     |
| `/yoke usher [YOK-N]`         | Deployment pipeline. Halts on capability gaps and approval gates.                        |
| `/yoke approve YOK-N`         | Approve a Yoke-handled human gate.                                                     |
| `/yoke do`                    | Autonomous session orchestrator.                                                         |
| `/yoke charge`                | Direct-mode: next runnable item from the frontier.                                       |
| `/yoke feed`                  | Direct-mode: refresh frontier, materialize new work.                                     |
| `/yoke strategize`            | Direct-mode: guided SML review.                                                          |

### Maintenance

| Command                            | Purpose                                               |
| ---------------------------------- | ----------------------------------------------------- |
| `/yoke doctor`                   | 40+ health checks. `--fix` for auto-repair.           |
| `/yoke curate`                   | Process agent learnings → tickets + patterns.         |
| `/yoke resync`                   | GitHub bidirectional sync.                            |
| `/yoke freeze YOK-N`             | Park an item.                                         |
| `/yoke thaw YOK-N`               | Unfreeze.                                             |

---

## Architecture

Yoke centers on seven specialized subagents, three orchestration skills (Shepherd, Conduct, Usher), a Postgres-backed state bus, and a dispatch loop for epic task execution. All state is SQL-first — agents write via `runtime.api.*` Python owners, renderers generate markdown views, and Postgres wins on any conflict.

**Multi-harness:** Any agent runtime that can run the operator command surface can attach to Yoke through a thin harness adapter. Yoke ships current adapters for Claude and Codex, with the shared contract documented in `docs/harness-bootstrap.md` and `docs/harness-adapter-template.md`.

```
AGENTS.md                            # Always-on project rules (CLAUDE.md is a compat symlink)
.yoke/strategy/                    # rendered strategy docs (DB-authoritative)

.yoke/
├── BOARD.md                         # Auto-generated project-local board view
├── board.json                       # Project-local board renderer settings
├── board-art                        # Project-local board presentation art
└── lint-config                      # Project-local hook guard policy

runtime/api/
├── cli/db_router.py                 # Unified DB access surface
├── service_client.py                # Public backlog + session mutation surface
├── engines/                         # doctor, merge_worktree, resync, repair_status
├── domain/                          # Hooks, renderers, in-process helpers
└── tools/                           # Executors, API server, test runner

.agents/skills/yoke/               # Root skill + per-command skills
.claude/agents/                      # Generated adapter files (yoke-*.md)
```

> For installation, configuration, and operator rules, see [docs/local-setup.md](docs/local-setup.md).

---

## Ouroboros — Self-Improvement

Every subagent answers three questions at session end: What went wrong? What process improvements? What game-changing ideas? Observations log to `ouroboros_entries`. A health scanner (`/yoke doctor`) runs 40+ checks. A system simulator (`/yoke simulate --system`) traces coherence gaps. A curator (`/yoke curate`) clusters learnings into tickets.

The flywheel: agents work → reflections capture learnings → curator creates tickets → tickets fix structural issues → faster delivery each cycle.

---

## Multi-Project Support

Each project is a registered git repository with its own deployment flows and configuration. Every item has a non-null integer `project_id`. Local checkout context is machine-resolved from `~/.yoke/config.json`; board rendering defaults to `.yoke/BOARD.md` and reads project-local renderer settings from `.yoke/board.json`.

```sh
yoke config example
yoke status
```

---

## FAQ

- **What's the minimum flow?** `/yoke idea` → `/yoke advance YOK-N implementing` → `/yoke usher YOK-N`
- **What does conduct do?** Single-item execution: Engineer → Tester loop until `implemented`.
- **What happened to PRD files?** Deprecated. `items get YOK-N body` is the spec view.
- **What if a harness session stops?** The Engineer commits incrementally. `/yoke conduct YOK-N` resumes.
- **Can subagents talk to each other?** No. Information flows via SQL state and structured feedback.
- **Does Ouroboros only improve Yoke?** No — it operates on every managed project.
- **What does `needs-capability` mean?** A delivery stage requires infrastructure not yet configured. Configure it, then re-run `/yoke usher`.
- **What does `awaiting-approval` mean?** A run is paused for human approval. Approve via `/yoke approve`, then re-run `/yoke usher`.

---

## Contributing

Yoke is [Fair Source](https://fair.io): the source is published to read,
audit, and contribute to, while the product installs as packaged wheels.
[CONTRIBUTING.md](CONTRIBUTING.md) covers working on the source — including
the explicit activation step (`yoke dev setup`) that binds a checkout (cloning
alone activates nothing), the test workflow, and the CLA signed on your first
pull request.

---

## License

Yoke is [Fair Source](https://fair.io) software: source-available under the
[Functional Source License, Version 1.1, ALv2 Future License](LICENSE.md)
(FSL-1.1-ALv2). Each version converts to the Apache License, Version 2.0 two
years after its release. Licensor: Benjamin Bauman.
