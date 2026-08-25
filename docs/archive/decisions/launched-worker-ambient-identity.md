# A launched worker's identity arrives in its environment, or not at all

## What was broken

Every background-launched Fleet worker needed the operator-debug
`--session-id` override on every control-plane call. The QA case runner
failed outright with `actor_session_missing`; watcher wrappers minted
captures under a literal `session-unknown` directory that the session-cwd
guard then refused; and a nested dispatch lost an explicit override
mid-invocation — `yoke merge item --session-id X` landed the GitHub merge
and then refused the evidence write, leaving a merged item with no
evidence until manual recovery.

## Why the obvious fixes do not work

The natural reading is that the relay should stamp identity at spawn and
write a process anchor at bind. Neither is possible for `claude --bg`.

**The relay does not know the id at spawn.** `session_relay_claude` runs
`claude --session-id <job_id> --bg <instruction>`, but `--bg` mints its
own session regardless. That is precisely why the adapter then scrapes
the `backgrounded · <short-id>` line and resolves the real UUID through
`claude agents --all --json` before binding it. One observed launch
passed job id `e7a6ed0d…` and bound session `f249aea0…`.

**There is no pid to anchor.** `claude --bg` hands the work to a
pre-existing `claude daemon run` process. The spawned CLI exits
immediately, and the shells that do the work descend from pooled
`bg-pty-host` → `bg-spare` processes the daemon owns, whose environment
was fixed before any launch existed.

**Those spares are reused, so anchors actively mislead.** A registry
entry observed live held `session_id: ""` with
`shared_by_multiple_sessions: true` and seven contending session ids —
one per worker the pool had served. Worse, `ps` reports their command
names with a role suffix (`claude bg-spare`), which matches no entry in
`HARNESS_PROCESS_BASENAMES`, so `find_nearest_harness_anchor` frequently
finds no harness ancestor at all. Anchor ambiguity here is structural,
not incidental, and it worsens with fleet concurrency.

## What was actually wrong

Claude Code already stamps `CLAUDE_CODE_SESSION_ID` into every subprocess
it spawns, for a background agent exactly as for an interactive session,
and it matches the registered `harness_sessions` row. Yoke's ambient
chain read `CLAUDE_SESSION_ID` — a name no Claude Code version exports
and which nothing in the tree ever set outside three test monkeypatches.
The Claude fast path had therefore never fired, and every claude-cli
session had been leaning entirely on the anchor backstop that launched
workers cannot use.

The fix is to read the name the harness actually sets. The wrong name was
retired rather than aliased: a fallback to a variable nothing sets is not
compatibility, it is a second thing to keep true.

## The consequences that follow

- **The relay must keep stripping identity from the child.**
  `native_session_environment` removes every `AMBIENT_ENV_VARS` name from
  the spawned environment. With the corrected chain that matters more,
  not less: the worker must receive its own id from Claude, never inherit
  the launching session's.
- **An explicit override has to survive the whole invocation.** The CLI
  stamps `--session-id` into the environment for the duration of one
  invocation, so the nested half of a delegating command re-resolves to
  the identity the operator named instead of finding nothing.
- **A session-scoped path refuses rather than minting one that will be
  denied.** Watcher-capture minting asks for a vetted session segment and
  raises inside a harness session rather than producing a
  `session-unknown` path whose later denial names the path instead of the
  identity gap. An operator's own terminal is legitimately session-less
  and keeps the placeholder; harness presence is read from the harness's
  own markers, because the process tree cannot answer the question for
  exactly the workers that need it answered.
