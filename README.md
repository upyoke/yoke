# Yoke

**New to Yoke? Start with [Getting started](https://upyoke.com/docs).**
It explains what Yoke is and how to use it. This README is for developers who
want to build, test, or contribute changes to Yoke's source.

Yoke is a control plane for humans and coding agents to plan, build, test,
and deploy software together.

[Self-hosting](docs/public/guide/self-hosting.md) ·
[Contributing](CONTRIBUTING.md) ·
[License](LICENSE.md)

---

## How it works

- **Universe** — the home for your projects, work items, strategy, and
  configuration. It lives in Postgres: on your machine, on your own server, or
  at upyoke.com.
- **Projects** — each project is a repository (or, for Task work, no
  repository) with its goals, workflows, deployment flows, and QA.
- **Work items** — Dash, Issue, Epic, Blitz, and Task. Each item is pinned to a
  versioned workflow whose stages run from idea to `done`, where `done` means
  delivered and verified with evidence, not just merged.
- **Agents** — Claude Code, Codex, and Cursor sessions do the work.
  Repository implementation
  runs in isolated git worktrees, with claims and dependency checks to
  coordinate sessions and machines working in parallel. Specialized roles
  (product manager, architect,
  engineer, tester, simulator, QA walker, and others) handle planning,
  building, and checking.

Read more: [Concepts](docs/public/start/concepts.md) ·
[Workflows and work items](docs/public/guide/work.md) ·
[Delivery](docs/public/guide/delivery.md) ·
[QA](docs/public/guide/qa.md)

## Install

Open Claude Code, Codex, or Cursor and say:

```text
install upyoke.com
```

Your agent installs Yoke, walks you through setup, and then runs onboarding:
it reviews your project, helps you write a strategy, and sets up testing and
deployment. Afterward, open a new session in your project folder and run
`/yoke steer` to direct the work.

Prefer a terminal?

```bash
curl -fsSL https://upyoke.com/install | sh
```

The installer needs only a shell and `curl`. It installs `uv` if missing and
runs Yoke on a managed Python 3.11–3.14; your system Python is unchanged.
Rerun it to upgrade.

**Supported platforms:** macOS (local mode needs macOS 15+), Linux with glibc,
and Windows through WSL2.
**Note:** setup turns off command-approval prompts and sandbox limits in the
agent tools it installs into, so Yoke-driven sessions can run unattended.

Read more: [Installation and setup](docs/public/guide/setup.install.md) ·
[Agent setup](docs/public/start/agent-setup.md) ·
[Terminal setup](docs/public/start/terminal-onboarding.md) ·
[Install reference](docs/public/start/install.md) ·
[Windows and WSL](docs/public/start/windows-wsl.md) ·
[Uninstall](docs/public/start/uninstall.md)

## Choose where your universe lives

| Mode | Where it runs | Who can use it | Start with |
| --- | --- | --- | --- |
| **Local** | Embedded Postgres under `~/.yoke/` | You, on this machine only. Free, no signup. | `yoke init --local --admin-name "Your Name"` |
| **Self-hosted** | Your server, via Docker | You and your team, from any machine | `yoke self-host init --admin-name "Your Name" --start` |
| **Hosted beta (upyoke.com)** | upyoke.com | You and your team (needs a beta code) | Pick **upyoke.com** in setup |

Teammates join a self-hosted or hosted universe with `yoke connect <url>`
after an invite. You can move a universe between modes:
`yoke universe export` writes one portable archive, and
`yoke self-host import` restores it.

Read more: [Modes](docs/public/start/modes.md) ·
[Hosting modes](docs/public/guide/setup.hosting.md) ·
[Self-hosting](docs/public/guide/self-hosting.md) ·
[Universe portability](docs/public/guide/universe-portability.md) ·
[Team collaboration](docs/public/guide/access.collaboration.md)

## Work with Yoke

```text
/yoke onboard          set up a project: strategy, testing, deployment
/yoke steer            direct the work from one session
/yoke dash "fix login" file and finish a small change end to end
/yoke idea "..."       capture work for later
/yoke charge           take the next ready item
/yoke usher APP-12     merge, deploy, and verify an item
```

The **web dashboard** shows projects, strategy, work items, agent sessions,
QA, and deployments, and is where you answer questions and approvals. Run
`yoke ui up` for local and self-hosted universes; hosted universes use
[app.upyoke.com](https://app.upyoke.com).

Read more: [Steering and fleet control](docs/public/guide/sessions.md) ·
[Dashboard](docs/public/guide/dashboard.md) ·
[Skills and commands](docs/public/agents/commands.md) ·
[CLI reference](docs/public/cli/index.md) ·
[Harnesses](docs/public/agents/index.md)

## Source, forks, and contributing

Yoke is [Fair Source](https://fair.io). The source is public so you can read,
audit, and contribute to it. The product you run is the packaged install;
cloning this repository changes nothing about the Yoke on your machine.

- **Contribute:** [CONTRIBUTING.md](CONTRIBUTING.md) covers cloning,
  running tests, binding a checkout with `yoke dev setup`, and the
  [CLA](CLA.md) you sign on your first pull request.
- **Run a private fork:** [Maintaining a private fork](docs/public/projects/private-forks.md)
  covers building your own wheels and server.
- **Understand the code:** [Architecture overview](docs/OVERVIEW.md) and the
  [internal docs index](docs/README.md). Contributors can run
  `yoke dev yokepedia` to browse a map of every rule, skill, role, and
  document Yoke gives to people and agents.
- **Add a harness:** [Harness bootstrap](docs/harness-bootstrap.md) and the
  [adapter template](docs/harness-adapter-template.md).

## License

Yoke is source-available under the
[Functional Source License, Version 1.1, ALv2 Future License](LICENSE.md)
(FSL-1.1-ALv2). You may use, modify, and redistribute it for any purpose
except a competing commercial offering. Each version becomes Apache 2.0 two
years after release. Licensor: Benjamin Bauman.
