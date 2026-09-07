# Session surface-version observation

## Why registration observes rather than inherits

A session's `harness_sessions.executor_version` names the build that session is
actually running. It is observed — the surface's own executable is asked, or a
recent recorded answer is reused — rather than inherited from whatever the
launcher put in the environment. A launcher's stamp describes what some earlier
process believed, and a pooled or pre-warmed harness process keeps that belief
long after the binary underneath it has been replaced.

## The vocabulary boundary that made every claude-cli session versionless

Observation is keyed on a **closed surface vocabulary** — `claude-cli`,
`claude-desktop`, `codex-cli`, `cursor-desktop`, and the rest of
`EXECUTOR_EMOJI`. The shared probe cache, the relay heartbeat's inventory, the
launch preview, and the version floors in `surface_versions` all speak it.

A harness names its own surface in its **family-relative** vocabulary. Claude
Code exports `CLAUDE_CODE_ENTRYPOINT=cli`; Yoke's own native launcher sets the
same marker. Codex and Cursor differ: their entrypoint resolvers already compose
a family-qualified surface (`codex-cli`, `cursor-desktop`) before returning it,
so only the Claude family ever handed a bare token onward.

Registration passed that bare token straight to the version observer. `cli` is
in no surface vocabulary, so the shared cache held no entry for it and no probe
command matched it — the observer answered "unknown surface" with the same empty
version it uses for "the probe failed", and the row stored NULL. Meanwhile the
server-side `canonicalize_executor` composed the *same* token into `claude-cli`
for `executor_surface`, so the row named a surface whose version it claimed not
to know, on a machine whose cache, heartbeat, and launch preview all agreed on
one. Because `surface_version_meets_floor` is false for an empty version, no
operator binding could rescue such a session: it satisfied no declared floor.

The fix composes the entrypoint into the family-qualified surface at the one
place the version is observed, so the surface a session stores and the surface
its version is read for are the same value.

Two mechanisms were suspected first and ruled out by direct observation from a
live hook process: the hook context resolved the same `relay_state_dir`
(`~/.yoke/relay`) as every other reader, and `resolve_relay_instance` did not
raise. Composing the token was the whole of it.

## Why an empty observation is never silent, and never the answer

Two invariants follow from that failure and are enforced by the observer:

- **An unobservable surface is not a versionless one.** A live probe that fails
  falls back to the newest version the shared cache ever recorded for that
  surface, at any age, marked `cache_fallback` rather than passed off as a fresh
  observation. Writing an empty version instead would convert a surface that
  briefly could not answer into one no version-gated route will ever accept.
- **Every empty or stale answer names its cause where operators already look.**
  Each attempt — successful or not — is recorded on the surface's shared-cache
  entry with its verdict, its error, and the reading caller's own source and
  reason. Reading the cache and probing no longer swallow their exceptions:
  a reader that cannot answer says why.

The fallback is scoped to the version *observation* readers use at
registration; the relay inventory that advertises which surfaces a machine
can wake answers from the same shared cache, at any age, for a related but
distinct reason below.

## Why the heartbeat's inventory keeps naming a surface past its freshness window

The relay's cache-backed heartbeat (`collect_cached_inventory`) does not
itself probe — it publishes whatever the background probe cycle last
recorded, on a schedule independent of the heartbeat. Reading that record
through the same age bound the fresh-observation path uses (previously
`cached_surface_versions`) meant a heartbeat sent in the gap between "a
machine wakes from sleep" and "the next scheduled probe runs" published an
empty `surfaces` map for every surface whose reading had merely gone stale.
The Machines panel read that emptiness as `surface_absent` — a confirmed
"not installed on this machine" claim the relay had no evidence for.

`collect_cached_inventory` now reads through
`session_relay_surface_identity.cached_surface_state`, which returns two
facts kept deliberately apart:

- **Last-known identity, at any age.** A surface this machine has ever
  reported a version for keeps naming that version in `surfaces` regardless
  of how long ago the reading was taken. This is the fact that changed: it
  used to be age-bounded like the registration-time observation above, and
  now it is not.
- **Confirmed absence**, named separately, only when the most recent probe
  actively found the executable missing (`verdict == "missing"`, e.g. a
  `FileNotFoundError`). A confirmed removal overrides the last-known version
  rather than being masked by it, so an operator uninstalling a CLI still
  sees it reported as removed.

A surface whose probes are failing for some other reason (a timeout, an
auth error) is neither of these: it keeps its last-known version until
either a live probe succeeds again or one actively confirms it gone. That is
a narrower version of the risk the invariant above exists to prevent — a
stale version could in principle outlive a silent, non-removal failure for
as long as the background probe cycle takes to notice — traded deliberately
against the alternative already observed in production: a machine that
merely slept through one freshness window reporting six installed harnesses
as uninstalled.
