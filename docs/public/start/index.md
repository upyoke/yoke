# Get started

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > Get started
<!-- /yoke:breadcrumbs -->

Start with your coding agent. It installs Yoke, walks you through setup and
helps you begin work on your project. You choose where Yoke runs and approve
the changes; the agent handles the commands.

## Ask your agent to install Yoke

Open Claude Code, Codex or Cursor in your project's folder and say:

> Install Yoke from upyoke.com and help me set up this project using agent mode.

You do not need a Yoke source checkout. On Windows, run your agent and keep
your project inside [WSL Ubuntu](windows-wsl.md).

The agent follows the installer and uses `yoke setup --agent` to continue.
It presents setup's questions one at a time and explains the choices.
[Agent setup](agent-setup.md) describes the commands and replies for the agent;
[Install](install.md) covers prerequisites and recovery.

## Choose where Yoke runs

Your agent will ask where to keep your work:

- **This machine:** a private local universe, reachable only from this computer.
- **A team server:** connect to a Yoke server you or your team already run.
- **Host a server here:** create a server for a team or multiple computers;
  this needs Docker.
- **upyoke.com:** hosted by Yoke; private beta, requiring a beta code.

A universe holds your projects and work records. [Modes](modes.md) explains
these choices and how to switch later.

Your agent shows what setup will change before you approve Apply. When browser
sign-in or machine approval is needed, it gives you the link; you complete that
step yourself. Then the agent continues setup with your chosen project.

## Begin work on your project

Follow the final setup instructions. If a new agent session is needed, open it
in the project folder as directed. Your agent checks that the session is ready
and follows Yoke's next action.

Ask it:

> Help me onboard this project, understand its existing work and choose a first
> small change to deliver.

The agent uses Yoke's onboarding guidance to capture your goals and existing
work, then helps you file and carry out the first change. You can describe what
you want in ordinary language; you do not need to file items with CLI commands.
[Concepts](concepts.md) explains the terms you will encounter.

## Optional: set up directly in a terminal

If you prefer to run setup yourself, use [Terminal setup](terminal-onboarding.md).
You can return to your coding agent after installation.

<!-- yoke:contents -->
- [Agent setup](agent-setup.md) — Recommended setup through your coding agent; commands and replies.
- [Install](install.md) — Installation prerequisites, configuration details and recovery.
- [Modes](modes.md) — Choose local, hosted or self-hosted ownership.
- [Concepts](concepts.md) — Understand universes, projects, items and workflows.
- [Project installation](project-install.md) — Install repository guidance and manage source launcher ownership.
- [Windows and WSL](windows-wsl.md) — Keep Yoke, agents and checkouts inside supported Linux on Windows.
- [Terminal setup (optional)](terminal-onboarding.md) — Set up Yoke yourself in a terminal instead of through your agent.
- [Uninstall](uninstall.md) — Preserve chosen data and remove machine or project guidance.
<!-- /yoke:contents -->
