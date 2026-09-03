# CLI and config

## CLI

After install, `yoke` is on PATH and always runs the **main checkout's**
installed packages (not a linked worktree's source), unless you re-point the
editable install for source-dev.

Common operators:

```bash
yoke status
yoke onboard
yoke ui up
yoke items get PREFIX-N
yoke items get PREFIX-N body
yoke board rebuild --print-only
yoke doctor
```

Harness skills (`/yoke do`, `/yoke idea`, …) call the same function-call
surface; CLI adapters are the operator/debug shape. Prefer
`yoke <subcommand> --help` for flags.

## Machine config

`~/.yoke/config.json` holds machine-local connections and tunables: which
environment is active, API URLs, local paths. Secrets for capabilities live
under `~/.yoke/secrets/` (not in the repo).

Launch defaults retain the scalar `preferred_session_models` map that the
previous release can read. Context stays encoded in each native model
selector, while effort lives in the additive
`preferred_session_reasoning_efforts` map:

```json
{
  "preferred_session_models": {
    "claude-cli": "claude-opus-4-8[1m]",
    "codex-cli": "gpt-5.6-sol"
  },
  "preferred_session_reasoning_efforts": {
    "claude-cli": "max",
    "codex-cli": "xhigh"
  }
}
```

Both maps are machine-local and travel on that machine's relay heartbeat.
After placement, each knob resolves independently: its explicit launch flag >
the chosen machine's advertised value > the vendor default. The caller's map
never decides a launch running elsewhere. Preview shows the raw request and
the effective selection with the machine setting that supplied each default;
the launch record retains both, and the bound session shows the effective ask
beside provider-attested served facts.

A fresh installer/onboard write seeds both keys with every launchable harness
surface. Blank model or effort means unset. Validation rejects non-string
entries, invalid selectors, unsupported effort values, and combinations the
named CLI cannot encode. Existing machine files are not rewritten during
rollout. `yoke status` and `--list-models` describe this machine's maps;
preview a launch to see another machine's effective defaults.

`yoke session-control launch preview` and `create` accept the three flags.
`--context-window` accepts a token count or compact form such as `1m`.
`--list-models --surface SURFACE` prints Cursor's native
`cursor-agent --list-models` result or the documented Claude/Codex IDs,
plus accepted effort and context values. Claude maps context 1M to the
model's `[1m]` selector and effort to `--effort`; Codex maps effort to
`-c model_reasoning_effort=...` and refuses explicit context; Cursor folds
effort and context into its bracketed `--model` value. An unsupported knob
is a preview refusal named for the harness and knob. A combination the
provider rejects at run time fails as `model_combo_unsupported`, retains a
bounded vendor message in launch evidence, and never retries under defaults.

## Launched sessions run unattended

A session the launch plane starts is an autonomous worker with nobody
watching its terminal, so every launch and every wake engages the harness
permission bypass: Claude Code is launched with
`--dangerously-skip-permissions`, Codex with approvals and sandbox bypassed
(`--dangerously-bypass-approvals-and-sandbox` on the CLI route, the same
posture as thread parameters on the app-server route), and Cursor with
`--force` alongside `--trust` on the CLI route. Cursor's ACP launch route
takes no such flag: the relay answers each permission request itself and
owns the terminals commands run in, so it is unattended already. This is
unconditional for launched sessions and changes nothing about a session you
start yourself.

One native gate can still refuse: Claude Code declines a bypassed background
launch until the machine has accepted the bypass disclaimer once. The launch
reports `permission_bypass_unaccepted` with the recovery step — run
`claude --dangerously-skip-permissions` interactively on that machine, accept
the prompt, then retry.

## Connections

A connection is how this machine reaches a universe:

- **local-postgres** — in-process against a local DB
- **https** — relay to Cloud or self-hosted API

`yoke status` shows which connection is active.

## Local UI

```bash
yoke ui up       # start it detached, print the tokened URL
yoke ui          # same as `yoke ui status` — running or stopped, plus the URL
yoke ui down     # stop it
```

Serves the same universe workbench used on Cloud, against your active
connection (typically `http://127.0.0.1:8688`). `yoke ui up` runs the
server as a machine daemon rather than a terminal job: closing the window
leaves it serving, and on macOS a launch agent brings it back after a
reboot until you run `yoke ui down`.

The URL carries a session token — treat it like a password. The token is
stable per machine, so the URL you bookmark keeps working across up/down
cycles. The server binds loopback only and refuses remote-facing hosts.

## Project-local `.yoke/`

Installed into each managed repo: skills, agent adapters, hooks, policy,
and `.yoke/docs` (this public corpus). Board markdown under `.yoke/BOARD.md`
is a generated view — do not hand-edit it as source of truth.
