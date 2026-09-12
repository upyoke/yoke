# Headless Stop continuation is observed, not inferred

Decision recorded 2026-09-12.

## Decision

`claude-cli` declares `relay_stop_denial_continuation="supported"`. A
Yoke-relay-launched Claude CLI worker that ends a turn holding a live
mid-lifecycle claim is held by the promised-work gate exactly as an
operator-opened Claude surface is, and keeps every escape the gate already
had: an armed queue landing, a terminal or wait stage, a turn that asked the
operator something, and the reinjection cap.

`codex-cli`, `codex-desktop`, and both Cursor surfaces are unchanged. Their
facts stay `none` because nobody has observed those surfaces continuing, not
because they are headless.

## Why

The fact was first written as `none` for every headless transport at once,
on the reasoning that a headless launch command "cannot accept another
prompt after its final Stop." That sentence is true and answers a different
question. Being headless bounds what can reach a worker *between* turns. A
denied Stop is not a new prompt: it returns to the turn the process is
already in.

An isolated canary on Claude 2.1.269 settled it. Invoked in the relay's own
shape — `-p`, permission bypass, `--output-format json`, an isolated
settings file with an explicit Stop hook and no inherited setting sources —
the hook returned `{"decision": "block", "reason": ...}` with exit 0 on the
first Stop. The same process continued, produced a second turn, and reached
the hook again with `stop_hook_active=true`, where the hook allowed. The run
exited 0 with `num_turns=2`. That block payload is byte-identical to what
`render_claude_stop` emits, so the gate's hold reaches the CLI as the canary's
did.

The cost of the wrong answer was not theoretical. Relay-launched Claude
workers are most of the fleet's execution, and for every one of them the gate
allowed the Stop and recorded deferred work at WARN instead of pushing the
worker back into the step it had left. A worker that stopped mid-item with a
live claim was recorded rather than continued — the one case the gate exists
to prevent.

## What this asks of the next surface

A surface moves to `supported` when a canary on that surface shows the same
three things: the hook's block returns to the same process, that process
produces another turn, and its next Stop carries the harness's own
already-held marker so the gate's cap can bound the hold. Transport shape
proves nothing either way. Until someone runs it, `none` and durable
deferral remain the honest answer.
