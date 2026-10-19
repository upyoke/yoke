# Get started

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > Get started
<!-- /yoke:breadcrumbs -->

Install Yoke, connect this machine to a universe, then ask your coding agent to
add your project and help file its first item. You need no Yoke source checkout.
Use a shell with `curl`; the installer offers to install `uv` if it is missing.
On Windows, start in [WSL Ubuntu](windows-wsl.md).

## Install

```bash
curl -fsSL https://upyoke.com/install | sh
```

The installer puts the `yoke` command on PATH and opens setup in an interactive
terminal. If setup did not open, run `yoke setup`. Open a new terminal if the
installer requests it. See [Install](install.md) for prerequisites and recovery.

## Choose a mode and connect

In setup's Account step, choose where Yoke and its database live:

- **This machine:** a private local universe; no signup or token.
- **upyoke.com:** a hosted universe with browser sign-in.
- **A team server:** your team's reachable server URL and its sign-in flow.
- **Set this machine up as a self-hosting server:** preview and create a server
  on a host you control.

[Modes](modes.md) explains ownership, networking and switching later. Review
setup's proposed writes before Apply. Browser sign-in and machine approval
remain human actions: open the offered link, sign in and approve your own
machine. Over SSH, use the [terminal copy view](terminal-onboarding.md).

To connect an already-installed machine separately, use the current CLI recipes:

```bash
yoke connect                 # hosted browser sign-in
# or: yoke connect https://<server>
yoke status
```

Expected: status names the active connection and reports this machine's setup.
For a local universe, choose **This machine** in `yoke setup` instead of running
`yoke connect`. A refusal names the cause and recovery; finish it before filing
work. See [onboarding](install.md#onboard-wizard) for server token options.

## Add your first project

Open Claude Code, Codex or Cursor yourself in your project's checkout. Ask its
agent: “Add this checkout to my connected Yoke universe, then run `/yoke onboard`
with me.” The agent checks existing project bindings, asks for the project's
identity and previews the supported project setup. Approve the choices it
shows; the agent adds the project. Yoke does not open an interactive agent
session for you.

Expected: the checkout carries its Yoke operating guidance, `yoke status` names
its project mapping, and `/yoke onboard` connects existing work to a first
delivery. If the project already exists and only needs guidance, see
[Project installation](project-install.md). [Concepts](concepts.md) explains
universes, projects, items and workflows.

## File your first item

Ask the agent to capture one small outcome with `/yoke idea`, or use the CLI
from any folder. Replace `P` with your project's slug. First read its current
creation instructions:

```bash
yoke workflow execution-instruction resolve --workflow dash --project P --full
```

Write `first-change.md` with the agreed outcome, scope and verification. Follow
the instructions you just read, then file and inspect it:

```bash
yoke items create "First small change" dash --project P \
  --spec-file first-change.md --execution-instructions-considered
yoke items list --project P --limit 5
```

Expected: the create reply names a new item ref and status, and the list shows
it. This records work; use the project's declared workflow to carry it through
implementation and verification. See [items and sessions](../items/index.md)
for the next supported action.

<!-- yoke:contents -->
- [Agent setup](agent-setup.md) — Relay setup questions and preserve human choices and secret boundaries.
- [Install](install.md) — Prepare the CLI and complete machine onboarding.
- [Modes](modes.md) — Choose local, hosted or self-hosted ownership.
- [Concepts](concepts.md) — Understand universes, projects, items and workflows.
- [Project installation](project-install.md) — Install repository guidance and manage source launcher ownership.
- [Terminal onboarding](terminal-onboarding.md) — Copy approval links and resume setup in local or remote terminals.
- [Windows and WSL](windows-wsl.md) — Keep Yoke, agents and checkouts inside supported Linux on Windows.
- [Uninstall](uninstall.md) — Preserve chosen data and remove machine or project guidance.
<!-- /yoke:contents -->
