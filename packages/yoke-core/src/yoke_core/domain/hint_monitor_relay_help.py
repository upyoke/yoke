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
matched lines arrive as wake events for the rest of that command's
lifetime. You do not call Monitor again to "continue tailing" - that
is the wake-loop bug.

Descriptions like "Continue tail" / "Continue tailing X" / "Tail
again" all describe the polling-loop misuse. Use subscription
framing instead: "Tail pytest progress" on the first (and only)
arm, then relay events as they arrive. The very FIRST Monitor call
on a capture is the only one you will make in this session for that
capture.

A second Monitor against the same capture file is denied at
PreToolUse, for the whole session - not just while a Monitor is
still armed. The deny is structural
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
- On each wake, relay the matched line as text (verbatim or a tight
  paraphrase that preserves the concrete signal: `pytest [47%]`,
  `FAILED tests/test_foo.py::test_bar`, `merge step 3 complete`).
  No commentary, no preamble, no status summary, no filler between
  wakes - silence between matched lines is correct.
- Relay means YOUR OWN visible output, and nothing else. Never
  forward a matched line to another session as a durable Fleet
  message (`yoke say`). A percentage, an elapsed-time poll, a
  watcher heartbeat, and a "still green" note are progress output:
  they cost the recipient an inbox row and a hand acknowledgement
  and change nothing about what it would do, and the send path
  refuses them as `body_not_substantive`. Message another session
  when a gate goes red, you are blocked, your instruction conflicts
  with what you see, you found a defect outside your scope, the item
  reached a terminal state, or you need a decision. A steering seat
  watches liveness with its own fleet watcher.
- The watcher wrappers (`watch_pytest`, `watch_merge`) coalesce
  repetitive ticks at the wrapper layer. An emitted line may carry
  a `(suppressed N ticks)` suffix; relay the line including the
  suffix, do not strip it.
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
  says "[ 65%]", relay "[ 65%]" - not "65%, all green".

When the background command completes, you are released. The
allowed inspection is exactly ONE `tail -80 <raw-capture>` of the
raw capture file. Do not arm another Monitor to "verify completion"
- the completion notification was the verification.
</system-reminder>"""


__all__ = ["HELP_REMINDER"]
