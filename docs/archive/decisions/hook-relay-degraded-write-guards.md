# Hook relay degradation: local write-guards stay strict

## Context

HTTPS hook evaluation splits one policy chain across the client and the
server. The client evaluates local-state policies against this machine
(git status, on-disk file content, bound workspace) and then POSTs the
rest. When that POST times out or returns a non-contract body, the
server half degrades to a no-op allow so the harness is never blocked
on an unreachable control plane.

Two failure modes collided on that degrade path. Blocking write-guards
that already had a local verdict were at risk of being diluted by the
degrade-to-allow, and advisory checks that need server enrichment (claim
rows, occupancy, recent tool-call history) had no honest answer without
the relay. Treating those the same way either drops protection or
invents a holder.

A second, related gap: Cursor sessions identify through the
hook-written cursor-session-map, not the env chain. The client can
resolve that map; the server cannot. If the client posts a payload with
an empty `session_id`, a later successful relay evaluates occupancy
against an unidentified caller and the caller's own claimed lane looks
foreign.

## Decision

When the relay is down, blocking write-guards stay strict on local
data. The client-side local-state subset has already run; its deny is
preserved through degradation and is never replaced by the no-op allow.
Guards whose verdict needs only this machine (destructive git, on-disk
line counts, bound-workspace probes) keep that verdict.

Enrichment-dependent advisory checks fail open with an advisory line.
A check that needs control-plane rows the client does not hold cannot
invent a deny; the degrade path keeps the client allow-stdout
(orientation, advisories) and names the degradation so the session can
see that server policy was not evaluated.

Caller identity is stamped on the client before the POST. The canonical
ambient chain (env, process-anchor registry, cursor-session-map)
resolves once at the hook-runner/relay boundary and writes
`payload.session_id` for the whole lint chain. The server never walks
the client's process tree or map. When identity still cannot be
resolved, a blocking write-guard names identity-resolution failure —
with the identify-yourself recovery — and never a foreign holder.

## Consequences

- Local-state denies still short-circuit the POST.
- A timed-out `/v1/hooks/evaluate` does not undo a client deny, and
  does not pretend occupancy was checked.
- Session-cwd and other DB-backed write-guards require a stamped
  session id from the client; an empty id is an identity failure, not
  a foreign-lane deny.
- Agents do not export session env vars to self-bootstrap that gap.
