# Install

```bash
curl -fsSL https://upyoke.com/install | sh
yoke onboard
yoke status
```

Prerequisites: a shell, `curl`, and `uv` (the installer can install `uv` with
consent). You are not asked to bring your own Python. Native Windows is
unsupported; WSL follows the Linux path.

## Onboard wizard

`yoke onboard` is a full-screen wizard:

1. **Install / PATH** — confirm the CLI
2. **Account** — where Yoke lives (this machine / team server / upyoke.com)
3. **GitHub** — optional App connect for product GitHub commands
4. **Project** — create, clone, import, or bind a checkout
5. **Review** — preview persistent writes, then apply

Flags: `--yes` for non-interactive apply; `--local` or `--connect URL` to skip
the destination picker.

## After onboard

Reload PATH if the installer added it (this terminal only), then open Claude
Code, Codex, or Cursor in your project folder and run `/yoke onboard`.

```bash
yoke status          # machine, env, credentials, checkouts
yoke ui              # local workbench (local mode)
# or open the Cloud dashboard after sign-in
```

Upgrade later by re-running the same curl installer. It resolves one channel
version for every Yoke product package.

The first command you run after an upgrade brings the rest of the install up
to the new engine. A machine-local universe has its schema converged before
the command is served — the same step a hosted container runs on boot.
Additive foreign keys match the live `environments.id` type so a universe
still on text keys reaches the ordered history that converts them. The convergence also declares a bounded `idle_in_transaction_session_timeout` for the session; recording it as the role's database default is best-effort, so a role that cannot alter its own defaults — or a second boot racing on the same catalog row — degrades with an `application_role_default_not_persisted` diagnostic on stderr instead of refusing every read. A project
checkout whose operating layer predates the new engine is named once, with
the `yoke project install <checkout>` that refreshes it. Run that when it
appears; otherwise the checkout keeps teaching the previous release.

## Project-only install

If the project already exists in the universe and you only need the repo
operating layer:

```bash
yoke project install ~/path/to/checkout
```

That materializes skills, agents, hooks, and `.yoke/docs` from the engine's
public docs corpus.

## Related

- [Modes](modes.md)
- [CLI and config](cli-and-config.md)
- [Projects](projects.md)
