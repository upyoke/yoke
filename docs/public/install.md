# Install

```bash
curl -fsSL https://upyoke.com/install | sh
yoke onboard
yoke status
```

Prerequisites: a shell, `curl`, and `uv` (the installer can install `uv` with
consent). You are not asked to bring your own Python.

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

```bash
yoke status          # machine, env, credentials, checkouts
yoke ui              # local workbench (local mode)
# or open the Cloud dashboard after sign-in
```

Upgrade later by re-running the same curl installer. It resolves one channel
version for every Yoke product package.

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
