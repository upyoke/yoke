# Yoke CLI and relay

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Yoke CLI and relay
<!-- /yoke:breadcrumbs -->

The Yoke CLI lets your agents read and update the shared work system. The relay runs in the background on each connected machine so Yoke can report its available harnesses, launch sessions, and support session control.

## What the Yoke CLI does

`yoke` is the command-line interface to your selected Universe. Its commands manage projects, strategy, work items, QA, deployments, and the other records your agents use to carry out work.

Commands return results and, when needed, a reason and next step. `yoke status` summarizes the current machine and connection. Use command help for precise arguments rather than inferring flags from a related command.

See [Command and technical reference](reference/index.md) for the command families.

## How agents use the CLI

Your agent chooses the appropriate command as part of a skill or workflow. Commands read current state and enforce permissions and workflow requirements when making changes. A chat instruction expresses your intent; the recorded command result establishes what actually changed.

Skills such as `/yoke onboard` are agent procedures, not shell commands with the same spelling. The agent reads the skill and uses CLI operations to perform it. You can keep working through conversation while asking the agent to show a result or explain a refusal when needed.

See [Agent guidance](guidance.md).

## What runs on your machine and in the Universe

The Universe's core and database hold shared records. Your machine holds the CLI, repository checkouts, coding harnesses, and local processes. In local mode these are on one computer; in self-hosted and hosted modes the core is remote.

A configured connection identifies the Universe and the actor for CLI requests. Each machine still needs its own working harness installation and model-provider sign-in. Hosting the control plane does not supply coding-agent credentials or move repository folders to every worker.

See [Hosting modes](setup.hosting.md) and [Projects](configuration.md).

## The relay: launches and liveness

The relay reports the machine's available harness surfaces and handles supported launches and session-control requests. A launched worker runs on that machine using its checkout, installed harness, and configured model access.

Fleet messaging can deliver through session hooks, while automatic waking depends on the supported surface and available relay path. A message may remain queued until you start the session's next turn; the dashboard explains that state.

On macOS the relay uses a user LaunchAgent. On Linux it uses a systemd user service; its lifetime depends on login and linger configuration. WSL requires its supported Linux setup. See [Linux relay supervision](../sessions/linux-relay.md) and [Windows and WSL](../start/windows-wsl.md).

## Connection and relay troubleshooting

Start with the selected connection and the affected machine. A reachable core, valid sign-in, active relay, and available harness are separate prerequisites. A failure in one does not prove the others are broken.

Ask your agent to inspect status and the named diagnostic. When evidence lives on another machine, Yoke's supported evidence-retrieval path can request bounded logs from its owner instead of assuming those files exist locally.

See [Operations and troubleshooting](operations.md), [Connection diagnostics](../cli/https-connection-diagnostics.md), and [Machine-local evidence](../databases/machine-local-evidence.md).
