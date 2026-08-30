# Monitor wakes resume the current turn

Decision recorded 2026-08-29.

## Decision

Claude Code's `Monitor` primitive resumes the **current turn**. Ending
that turn — by allowing Stop, or by the model going idle after the
Monitor tool_use completes — closes the Monitor reader. The paired
`yoke watch tail` then exits on `BrokenPipeError` with code 0, which
looks like a clean finish and leaves no wake. A session in that state
keeps its process and its work claim; `ended_at` stays NULL; heartbeats
freeze. External Fleet inject still reaches the process because it
never died.

That is not a harness process kill, a context-window abort, an output
limit, or a relay-lease expiry. It is turn-abandonment after Monitor.

The Stop promised-work gate therefore **holds** a Stop whose last
completed tool is `Monitor`, and does not spend the reinjection cap on
that hold. A parked session is the escape: park first, then Stop is
allowed. Teaching no longer says that waiting *is* ending the turn.

## Specimens

Session `02fbeca8-41bb-4eea-8bab-ebf5cadabe71` (`claude-cli` 2.1.251,
model `claude-opus-5[1m]`) on 2026-08-29:

- One `HarnessSessionStarted` at 16:58Z. No later start. `ended_at` NULL
  until a steering `SessionTerminated` at 21:27Z.
- Last tool before each freeze was `Monitor` (PostToolUse ~2.3–2.5s —
  arm, not a matched line): 19:31:23, 20:01:09, 20:40:26, 21:02:52.
- Three steering-seat wakes resumed the **same** process (19:53, 20:37,
  21:02) with no new episode.
- `ChainEndDeferred`: `promised_work_reinjected` at 18:03, 19:00, 20:01;
  `reinjection_cap_reached` **allow** at 21:03. The 19:31 freeze has no
  Stop in the ledger — the model ended the turn without the gate.
- Contrast: codex-cli `01a04f6b-fa9a-78f1-a751-bc872f2fcbb7` finished
  the same item in minutes (`idle_wake=none`; long commands stay in one
  `exec_command`). cursor-cli workers the same day did not freeze this
  way.

Field-notes 42807 and 42811 named the same shape earlier: a killed
background waiter is indistinguishable from still-waiting.

## Why the other hypotheses fail

- **Harness kills the process.** A killed native would not accept three
  later turns under the same `session_id` with no `HarnessSessionStarted`.
  Relay-verified process death (`docs/archive/decisions/relay-verified-process-death.md`)
  is a different path and was not this row.
- **Context or output limits mid-tool.** `HarnessToolCallCompleted`
  lands for the Bash/Monitor calls immediately before each freeze.
- **Relay lease expiry.** `RelayTransportRetrySucceeded` around resumes
  is `session_control.relay.claim` from the steering seat, not the
  worker dropping its lease.

## Operational doctrine (when a waiter is already dead)

The process-table liveness check still applies to a *dead native*. For
this freeze the native is alive, so that path will not fire. The
working recovery is: confirm `turn_posture=waiting` with a frozen
`last_tool_call_at` after Monitor, Fleet-inject or terminate-and-relaunch
on another surface, and let the QA gate adopt an already-concluded run
(`docs/archive/decisions/qa-gate-covering-run-adoption.md`) so a retry
does not re-dispatch.

## Alternatives considered

**Cap-allow Stop after three holds.** That is what 21:03 did. Allowing
Stop is what closes the reader.

**Foreground watchers for main-session claim holders.** Correct for
subagents (Monitor has nowhere to deliver after `SubagentStop`). Main
session still needs background+Monitor for streaming; the defect is
ending the turn, not arming Monitor.

**ScheduleWakeup as a mandatory companion.** A valid backup if Stop
never fires; not required once the gate holds Monitor-armed Stop and
teaching stops instructing turn-end-as-wait. A model that idles
without Stop remains a residual vendor gap; Fleet inject is the
operational backstop for that case.
