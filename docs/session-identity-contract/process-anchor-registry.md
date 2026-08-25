# Process-Anchor Registry (shell-side ambient identity)

How step 2 of the ambient chain resolves, and why it refuses a pid
that cannot name one session. The chain itself lives in
[`session-identity-contract.md`](../session-identity-contract.md).

Every registration pass through `_register_from_hook` records the hook
process's nearest harness ancestor — the per-session agent binary
(executable basename `claude` / `claude-code`), never the shared desktop
app shell — into `<machine-home>/session-anchors/<anchor-pid>.json`
(`yoke_core.domain.session_process_anchors`; atomic tmp+rename, no
locking). Each record carries `session_id`, `transcript_path` (when the
hook payload had one), `anchor_pid`, `anchor_start_time` (opaque
`ps -o lstart=` string, equality-compared to defeat pid reuse),
`anchor_process_name`, and `registered_at`. The anchor write is
best-effort and independent of DB registration success, so shell-side
identity survives a briefly unreachable control plane.

## A pid is only an anchor when it belongs to one session

The registry maps a pid to a session, so a pid shared by concurrent
conversations cannot identify any of them. Two defenses keep a shared pid
from answering:

- **Known session-hosting processes are never anchors.**
  `process_ancestry.MULTIPLEXED_PROCESS_BASENAMES` lists the pids hosting
  every concurrent conversation at once — the Codex app server and its
  code-mode host, the Cursor agent, and Claude's pooled background-agent
  hosts, handed to successive workers so the pid names a pool slot. The
  anchor walk stops at one rather than continuing to an ancestor that can
  only be more widely shared: above a pooled host that ancestor can be an
  ordinary per-session `claude`, and walking through would resolve a
  worker to that session. Step 1 still covers each, from its own family.
- **Contention is recorded, not overwritten.** When a second live session
  resolves the same anchor pid — same pid *and* same start time, so not a
  reused pid — `record_session_anchor` replaces the record with a
  `shared_by_multiple_sessions` marker instead of taking the pid over.
  Resolution stops at such a record and returns `None`. Silently
  overwriting would hand the displaced session's shell processes the new
  session's id, which is worse than not resolving: an
  `actor_session_missing` refusal is visible, and acting under another
  session's identity is not.

Both defenses fail toward step 3: an unresolvable identity is a gap to
report, a confidently wrong one a correctness bug. A background-launched
Claude worker has no usable anchor at all — see [`launched-worker-ambient-identity.md`](../archive/decisions/launched-worker-ambient-identity.md).

## Contention is a marker that heals, never a latch

A contention marker records the state it refuses over, and every anchor
write re-decides tenancy (`yoke_contracts.session_anchor_contention`):

- The marker carries `contending_session_ids` plus a
  `last_writer_pid` / `last_writer_argv` breadcrumb, so a contended pid is
  attributable instead of blank.
- The **writer is always a live candidate** — its hook event is proof of
  the process even while its session row is transiently ended.
- A recorded contender **drops out** when the probe positively says it is
  not a live session — its row is ended, or it has no row at all (rows are
  never deleted, so an unregistered id is not a conversation on this
  control plane; that is the anchor-poisoning class). Probed through the
  `sessions.list` single-session projection, over either transport. A
  *clean* registry record anchoring the contender to a different live
  process also drops it — one conversation has one per-conversation
  process, so a live home elsewhere means this pid's claim on it was
  written in error. A failed probe keeps the contender: genuine ambiguity
  still fails closed.
- One live candidate left → the record becomes that session's clean
  anchor again. Two or more → the marker persists, now naming them, and
  the engine-side writer emits `SessionAnchorContentionObserved` for
  ledger visibility. `HC-session-anchor-contention` flags any live marker
  whose recorded contenders are not two-or-more live sessions.

Markers written before contender recording heal the same way: the next
write from the surviving tenant finds a single candidate and reclaims the
pid.
