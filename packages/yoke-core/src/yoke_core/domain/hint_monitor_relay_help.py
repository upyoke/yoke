"""Full Monitor relay rules, shown on ``python3 -m yoke_core.domain.hint_monitor_relay --help``.

The injected PreToolUse reminder is the short ``DEFAULT_REMINDER`` in
:mod:`yoke_core.domain.hint_monitor_relay`. This module holds the complete
text so the hook context stays a few lines while the deny-side coverage
still has one canonical home.
"""

from __future__ import annotations

HELP_REMINDER = """\
<system-reminder>
Monitor is a SUBSCRIPTION, not a poll. Frame this in your head before
your first call: you arm Monitor ONCE per background command, and
matched lines arrive as wake events until the command ends or the
subscription expires. You do not call Monitor again to "continue
tailing" a live subscription - that is the wake-loop bug.

A Monitor subscription lives at most its timeout_ms deadline (the
capped maximum is the manifest's agent_wake
idle_wake_subscription_limit_seconds). Arm a long tail at that maximum.
When the expiry notice arrives and the background command still runs,
re-arm the SAME tail against the SAME capture; the tail resumes after
the last line it delivered. Never relaunch the wrapper.

Descriptions like "Continue tail" / "Continue tailing X" / "Tail
again" all describe the polling-loop misuse. Use subscription
framing instead: "Tail pytest progress" on the first (and only)
arm, then relay events as they arrive. The very FIRST Monitor call
on a capture is the only one you will make for that capture until its
expiry notice.

A second Monitor against the same capture file is denied at
PreToolUse while an earlier one could still be subscribed - whether
or not its tool call has completed. The deny is structural
(``yoke_core.domain.lint_long_command_polling.evaluate_duplicate_monitor``):
identical re-arms, different-filter re-arms, post-completion re-arms,
and bare ``tail -f ... | grep ...`` rewrites are all caught.
``# lint:no-monitor-duplicate-check`` is audit-only; the rule still
denies. Why so strict: Monitor's tool_use completes within ~0.3s of
setup; the underlying watch_tail subprocess keeps running until the
exit sentinel. Re-arming spawns a fresh watch_tail and orphans the
prior one. Operational data showed dozens of orphaned watch_tail
processes accumulating per 5-minute pytest run before the rule
tightened.

What you DO do during a Monitor-armed background command:
- On each wake, write one plain-language sentence saying what changed
  that the user would care about, and keep its concrete signal: the
  item, PR, failing test or terminal state (`FAILED
  tests/test_foo.py::test_bar`, "PR #12 merged", "pytest is at 47%").
  When the matched line changes nothing worth reporting, write nothing.
  Never paste the raw line or a multi-line report block (`=== BEGIN
  ... REPORT ===`, status fields) into chat. No preamble and no filler
  between wakes - silence between wakes is correct.
- Relay means YOUR OWN visible output, and nothing else. Never
  forward a matched line to another session as a durable Fleet
  message (`yoke say`). A percentage, an elapsed-time poll, a
  watcher heartbeat, and a "still green" note are progress output:
  they cost the recipient an inbox row and a hand acknowledgement
  and change nothing about what it would do. Keep them in your own
  visible output. Message another session only when a gate goes red,
  you are blocked, your instruction conflicts
  with what you see, you found a defect outside your scope, the item
  reached a terminal state, or you need a decision. A steering seat
  watches liveness with its own fleet watcher. Ending a turn sends no
  Fleet message; send terminal and other actionable worker reports
  deliberately with `yoke say --steering`.
- Routine progress never wakes you on its own: `yoke watch tail`
  holds `# watch_<kind> digest ...` lines and stall notices and hands
  them over in front of the next urgent line or the exit sentinel. A
  digest covers every signal between its middle dots in the order they
  happened; fold what it says into that wake's one summary sentence -
  do not unpack it into a turn per signal, and do not report only its
  last signal. Urgent lines still arrive the moment they happen. A bare
  tail needs no filter. An emitted line may also carry a
  `(suppressed N ticks)` suffix, meaning N numeric ticks were
  superseded by that one; the latest tick is the one to summarize.
- Parallel work in other tools (Read, Edit, unrelated Bash) is fine
  and encouraged between wakes.
- Do not emit no-op Bash calls to hold the turn while waiting
  (`echo 'waiting on deploy stage'`, bare `true`, decorative `date`).
  A side-effect-free command probes nothing and relays nothing.
  Do not Stop after arming Monitor while a claim is live: ending the
  turn closes the reader and the waiter dies with no wake.
- Avoid repeated peeks at the capture file
  (tail/head/cat/wc/grep/egrep/fgrep/rg/ls/awk/sed/less/more/file/stat/nl/cut/sort/uniq)
  while the owning command is running. The matched lines ARE the
  signal; the capture is for post-completion inspection.
- Do not spawn another `Bash(run_in_background)` whose body is
  `tail -f <capture>`, `sleep N && tail/cat <capture>`,
  `while [ ! -f <sentinel> ]; do sleep; done`, or another
  `watch_tail <capture>` against the same capture file. The
  armed Monitor IS the waiter.
- `/private/tmp/claude-<uid>/<project-hash>/tasks/<id>.output` is
  also a capture file - `TaskOutput` artifacts live there. The
  peek/waiter rules apply to those paths identically.
- Do not infer state that wasn't in a matched line. If the line
  says "[ 65%]", say the run is at 65% - not "65%, all green".

When `wait_mode=background-wake` says the caller's harness has a native
idle-wake primitive, completion releases that caller. The allowed
inspection is exactly ONE `tail -80 <raw-capture>` of the raw capture
file. Do not arm another Monitor to "verify completion" — the completion
event is verification only for that wakeable mode. `wait_mode=in-turn`
keeps the original foreground tool call alive and expects no notice.
</system-reminder>"""


__all__ = ["HELP_REMINDER"]
