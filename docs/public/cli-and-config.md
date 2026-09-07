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

`session_model_routing` is the separate, optional key that says which model
each tier of work asks for on a surface. It is a policy about work rather than
a fact about a provider account, so it is read from the machine composing the
launch — unlike the two default maps above, which come from the machine that
will run it:

```json
{
  "session_model_routing": {
    "cursor-cli": {
      "tier1": "cursor-grok-4.6-high",
      "tier2": "cursor-grok-4.6-medium",
      "excluded": ["cursor-auto"],
      "fallbacks": ["claude-opus-5-thinking-high"]
    },
    "claude-cli": {
      "tier1": "claude-opus-5",
      "tier2": "claude-sonnet-5",
      "worker_tier": "tier2"
    },
    "codex-cli": {
      "tier1": "gpt-6-astra",
      "tier2": "gpt-5.6-terra",
      "worker_tier": "tier2"
    }
  }
}
```

`tier1` is the model for demanding, ambiguous, or high-consequence work;
`tier2` is for bounded work a cheaper model already handles. `excluded` models
are never launched. A `fallbacks` entry is reachable only when the preferred
model's own billing pool is confirmed empty — an unreadable meter, a low
headroom reading, or room in a different pool is not confirmation, so a
fallback never starts spending a separate allowance by accident. Every key is
optional and a surface with no entry keeps the defaults above.

`worker_tier` is how a surface reserves its tier-1 model: ordinary work placed
on that surface routes to the named tier whatever the work kind asked for,
while the steering seat still takes tier1, as does a launch that names its
model explicitly. The example above reserves the Claude and Codex tier-1
models for steering or an explicit instruction and routes ordinary work to
tier2, and leaves the Cursor surface unreserved so its tier-1 model is the
ordinary worker there, with the Claude fallback reachable only on confirmed
pool exhaustion. That split is a machine-local operator choice, not a Yoke
default: a surface with no `worker_tier` routes every work kind to the tier
that kind asks for.

`yoke session-control launch preview --model M` reports each machine's quota
in the pool `M` actually bills to, under `REQUESTED MODEL POOL`, and ranks
machines by that pool's meter rather than by whichever window reads lowest.

`yoke session-control launch preview` and `create` accept the three flags.
`--context-window` accepts a token count or compact form such as `1m`.
`--list-models --surface SURFACE` prints this machine's configured defaults
beside its observed native availability (below), plus accepted effort and
context values. Claude maps context 1M to the
model's `[1m]` selector and effort to `--effort`; Codex maps effort to
`-c model_reasoning_effort=...` and refuses explicit context. Cursor passes an
exact advertised selector, such as `cursor-grok-4.6-high`; a separate matching
effort is encoded once, and a conflicting effort refuses. A base name plus
effort resolves only to an advertised variant. Cursor context is model-specific:
an explicit window requires that exact variant's native display label to name
it. Grok has no advertised 1M window; omit the context flag. A label establishes
a selectable option, never a served-session measurement, so unattested context
stays unknown. Preview and create use the chosen machine's native observations
for these checks. An unsupported combination is a preview refusal named for
the harness and knob, with a recovery step. A combination the
provider rejects at run time fails as `model_combo_unsupported`, retains a
bounded vendor message in launch evidence, and never retries under defaults.

## Selectable models are observed, not declared

Which models a surface will accept is a fact about the account and build on
one machine, so Yoke reads it from the surface rather than shipping a list.
Each relay poll refreshes a per-surface reading and carries it on the
heartbeat, so a model an account gains becomes visible to the fleet within
about a minute rather than within a release.

Discovery is per surface, and a surface with no adapter says so:

| Surface | Route |
|---|---|
| `cursor-cli` | `cursor-agent --list-models` |
| `codex-cli` | `codex` app-server `model/list` |
| every other surface | none declared; the reading says so by name |

Shipping one vendor's CLI adapter proves nothing about the same vendor's
desktop app or editor extension, so every known surface gets its own reading
rather than inheriting a sibling's.

Each reading names its own `status`:

| Status | Meaning |
|---|---|
| `ok` | the surface answered just now; `models` is current |
| `stale` | the last attempt failed; `models` is what it last published |
| `unsupported` | Yoke declares no listing adapter for this surface |
| `unknown` | the surface has never answered |

Only `ok` and `stale` carry models. **Neither `unknown` nor `unsupported` is
evidence that a model is unavailable** — a caller routing work reads the
status before the list. A failed probe never empties a list that was
populated: it keeps the models with their original observation time and flips
the status to `stale`, because an unreachable surface has not withdrawn
anything.

Each model entry carries what its vendor published: the selectable token, a
display description, that model's own reasoning options and default, and any
replacement target with its retirement time. Reasoning options are per model
rather than per surface — one installed app-server offers `ultra` on its
newest model and not on the one beside it.

Availability carries no dependency on researched pricing or tier data. A
model this machine can select today is reported today, whether or not
anything else is known about it.

Read it three ways:

```bash
yoke relay probe-models [--surface S] [--json]   # refresh this machine now
yoke session-control launch --list-models        # defaults beside availability
yoke steering report get                         # every machine in the scope
```

The relay refreshes on its own cadence during normal polling;
`yoke relay probe-models` is the bounded refresh for when you need the answer
before the next poll.

## Launched sessions run unattended

A session the launch plane starts is an autonomous worker with nobody
watching its terminal, so every launch and every wake engages the harness
permission bypass: Claude Code is launched with
`--dangerously-skip-permissions`, Codex CLI with approvals, sandbox, and hook
trust bypassed (`--dangerously-bypass-approvals-and-sandbox` plus
`--dangerously-bypass-hook-trust`; the app-server route uses equivalent
thread parameters where available), and Cursor with
`--force` alongside `--trust`. This is unconditional for launched sessions
and changes nothing about a session you start yourself.

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
