# Installation and setup

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Installation and setup
<!-- /yoke:breadcrumbs -->

**Open Claude Code, Codex, or Cursor and say:** `install upyoke.com`

Your agent installs Yoke, guides you through setup, and helps configure the project. You make the configuration choices and complete browser sign-in. After setup, `/yoke onboard` helps turn your existing project and plans into work Yoke can carry through delivery.

## Install Yoke

The public installer installs the released CLI and starts agent-guided setup. It installs `uv` and a supported Python interpreter when needed. Your agent follows the installer's next step rather than asking you to assemble a command sequence.

Yoke works with Claude Code, Codex, and Cursor. Setup discovers installed harnesses and configures their Yoke instructions, skills, hooks, and permissions. Review shows the changes before applying them, including settings that let background workers run unattended.

The [installation reference](../start/install.md) contains prerequisites, installer commands, and recovery instructions.

## Agent-guided setup

Setup asks one question at a time and saves each answer. Your agent presents the choices and continues from the saved position if the conversation or command stops.

You choose where your Universe runs: your computer, your own server, or Yoke's hosted service. See [Hosting modes](setup.hosting.md). You can connect an existing project, import or clone a repository, or create a new project. Setup recognizes existing Yoke configuration before proposing changes.

Complete sign-in and machine approval in your own browser. A browser code authorizes a particular connection; your agent should show the returned instructions and let you make that decision. GitHub connection is optional, and GitHub issue mirroring is a separate project choice.

Review the proposed changes, apply them, and follow the returned next action. Some harnesses require a new session to load newly installed hooks. Yoke's session check identifies whether yours needs that restart; there is no need to restart every harness by default.

For the exact agent protocol, see [Agent setup](../start/agent-setup.md).

## Onboarding

Once setup is complete, your agent runs `/yoke onboard`. It reviews the project and existing work, helps establish strategy and near-term priorities, and configures what the first dashes need to be tested and deployed.

Onboarding can reuse an existing application rather than replacing it with a scaffold. Together, you choose relevant tests, delivery settings, Packs, and database setup. Optional capabilities can be deferred. Credentials and infrastructure changes require the relevant choices and approvals; having a capability available does not mean every project must configure it.

Database onboarding can register a migration model or record that it will be attached later. It does not itself rehearse or apply migrations. See [Databases and migrations](databases.md) for the project-specific integration.

After `/yoke onboard`, `/yoke steer` vets proposed dashes and presents each for your approval before filing, then staffs and delivers them. It brings decisions to you one at a time. See [Steering and fleet control](sessions.md).

## Supported machines and prerequisites

The installer checks the machine before proceeding. Linux requires a glibc-based distribution. Local mode on macOS requires macOS 26.0 or newer for the embedded PostgreSQL build; a machine that cannot run that database can still connect to a remote core when its CLI prerequisites are met.

A working coding-agent sign-in is separate from Yoke sign-in. Setup's session check verifies registration, harness sign-in, and permission to run Yoke commands. Follow the named repair and rerun the check.

Version-specific platform requirements live in the [installation reference](../start/install.md), so check it before provisioning a new machine.

## Windows and WSL

Use WSL2 with Ubuntu, keep the repository in the Linux filesystem, and run Yoke and your agent CLI inside Linux. Setup configures systemd and, where supported, WSL's idle-shutdown setting so background work can continue after terminals close.

If setup requests a WSL restart, save your work before following it. Browser links can open on the Windows side while the agent and repository stay in WSL. See [Windows and WSL](../start/windows-wsl.md) for the supported path and recovery details.

## Manual terminal setup

If you prefer to answer setup questions directly, run `yoke setup --tui` in a terminal. It uses the same setup choices and review step. The wizard provides copy and browser-opening keys for links and codes, and saved progress lets you resume.

This is an alternative interface for installation, not a separate way to run your project. Return to your coding agent afterward and follow the readiness check and onboarding next action. See [Terminal setup](../start/terminal-onboarding.md).

## Updates, uninstalling, and retaining data

`yoke update` updates the installed release and reports the next step. Local mode updates the local server with the CLI; a self-hosted server has its own operator-managed update, and hosted servers follow hosted releases. Project guidance is refreshed when the update runs inside an installed project.

Removing the CLI from a machine and removing Yoke's layer from a project are different operations. Before uninstalling a machine that holds a Universe, choose whether to export a backup: there is no automatic backup. Hosted client removal does not remove the hosted Universe.

See [Remove Yoke](../start/uninstall.md) and [Universe portability, backup, and restore](universe-portability.md) before removing an installation that holds data.

## Troubleshooting installation

Ask your agent to read the exact failure and follow its recovery. PATH failures, missing harness sign-in, an unreachable server, and incomplete project installation require different repairs. Repeating installation without resolving the reported cause can leave the same problem in place.

`yoke status` reports machine and connection state. The saved onboarding checklist reports the next setup action and distinguishes configured, deferred, and unknown state. See [Operations and troubleshooting](operations.md) for broader diagnostics.
