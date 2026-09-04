# The relay closes the Claude jobs its ended sessions leave open

Decision recorded 2026-09-03.

The sibling path — the machine proving a native process is *gone* — is
[`relay-verified-process-death.md`](relay-verified-process-death.md). This
decision covers the inverse leak: a process that is alive long after its
session ended.

## Decision

Each poll cycle, after the verified-death report, a machine's relay names
every `claude bg-spare` process that is a used-up host: it has no children,
Claude Code's own session registry (`~/.claude/sessions/<pid>.json`) names
the session and background job it ran, that job's own state record has not
moved for one named idle threshold, the job is not mid-turn, and the spare is
not the newest one the daemon keeps warm.

Hosts whose job Claude already reports `stopped` are signalled directly —
SIGTERM, then SIGKILL after the termination grace period. Every other host
is put to the control plane through `session_control.relay.idle_hosts`,
which answers with the ones whose Yoke session has `ended_at` or
`terminated_at` set. Those jobs are stopped through Claude Code's own stop
path (`claude stop <background-job-id>`), by the job id Claude's own session
record already names, which closes the job so the daemon releases the
process. A host whose session the control plane reports live is left alone.

Every host stopped or signalled is reported back on the same function with
its pid, age, idle time, resident size, action, and result; the control
plane records each as a `HarnessSessionNativeHostReclaimed` event on the
session.

## Why

A Yoke session that ends — deliberately, through the empty-session end, or
by the stale-session sweep — tells the control plane and nobody else. The
Claude daemon that hosts the session still holds the background job open,
so the `bg-spare` process it runs in idles indefinitely at roughly half a
gigabyte resident. Ten such hosts, aged one hour to eight days, once held
2.1 GB on a machine with 44 MB free and 15 GB of swap in use; killing them
freed 5 GB of swap.

## Why a plain signal is not enough

A childless spare is not necessarily free. The daemon still tracks the job,
and it reads a signal on that process as a crash: it respawns the session
with a "this session was automatically restarted after its process exited
unexpectedly" prompt. One such restart replayed a report finished a week
earlier and tried to reach an orchestrator that had long since ended. So a
host is signalled only when Claude's own job record says `stopped`, and an
open job is always closed through Claude's stop path instead.

## Why every stop resolves through the per-pid record

A stop used to start from a native session id and ask `claude agents --all
--json` which background job carried it. That listing is read under a
64 KiB output bound, and a machine with a few hundred background agents
overruns it: the JSON arrives truncated, every resolution fails to parse,
and the stop is never issued. Observed live at 78 KiB and 275 agents, where
nine idle hosts were named correctly and none of them stopped.

Both relay paths now use one bounded per-pid record resolver. Idle-host
reclaim already knows the host pid and resolves that exact record. Deliberate
operator termination starts from Claude's native session id, scans the small
`sessions/<pid>.json` records individually, and selects the newest valid
record naming that session. The result carries both the pid and the job id,
which is exactly the id `claude stop` takes. Neither path reads the aggregate
agent listing.

A missing target record reports `session_record_missing`; a record set that
cannot be parsed or validated reports `session_record_invalid`. Both carry
the recovery to restore or have Claude rewrite the per-pid record and run
`claude stop <job-id>` from it, and neither falls through to signalling a
host the daemon may still own.

## Which hosts are left to reclaim

Yoke starts its own Claude workers as relay-owned processes, so they have
no daemon job and leave no host behind. What still arrives here is the
daemon's own population: sessions a person opened, and hosts left by
workers started before that changed. The path is narrower than the leak
that motivated it and is now a cleanup for the sessions Yoke does not
start, rather than a correction for the ones it does.

## Why the control plane answers rather than the machine guessing

The relay can see that a host is idle but cannot tell whether the session
behind it finished or is merely quiet through a transient disconnect that
the next hook event will heal. The row holds that fact — `ended_at` — and
only for sessions the machine runs, in projects the relay serves. A skipped
host always comes back with a named status, because a silent omission reads
exactly like a live session, and a live session is the one thing this path
must not touch.

## Why the idle threshold applies to the job record, not the process

Process age says how long the session has existed, which is unrelated to
whether it is finished: a worker two hours into an item is old and busy.
The daemon rewrites the job's state record throughout a turn and leaves it
still once the job is done or waiting, so "the record has not moved for ten
minutes" is Claude's own statement that nothing is happening. The threshold
is one named constant, `IDLE_HOST_THRESHOLD_SECONDS`, and the idle check
sits beside the childless check rather than replacing it.

## Rollout

`session_control.relay.idle_hosts` is a new registered function. A relay
running ahead of its control plane gets the typed skew answer, logs it, and
stops nothing it asked about; hosts Claude already reports exited are still
reclaimed locally, because that decision needs no control-plane fact. The
poll it rides on is unaffected either way.

## Alternatives considered

**Having the control plane name ended sessions to the relay.** The control
plane cannot bound that list: it does not know which ended sessions still
have a live host, so it would name every ended session on the machine, for
ever, or need a new column to mark hosts released. The relay's local scan
bounds the exchange to live idle hosts, which is usually none.

**Stopping the job from the hook that ends the session.** The empty-session
end runs inside the very session being ended, and the stale sweep runs on
the server with no hook at all, so neither place sees every end. The relay
poll is the one machine-side path that runs regardless of how the session
ended.

**Reaping every childless spare older than a threshold.** That is the
signal-on-a-tracked-host hazard above, observed live.
