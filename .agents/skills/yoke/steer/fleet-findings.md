# Acting on fleet findings

What the report gives you is a finding; what to do with each one is yours:

- **Available work** — staff it. An `!` row has waited past the staffing
  threshold; an unmarked row is simply available.
- **Steering messages awaiting a seat** — unacknowledged mail no live seat
  holds: parked reports and reports left by an ended seat. Acquiring that scope
  hands them over; acknowledged receipts are never inherited. Their unfinished
  actions must already be recorded in the standing plan before handoff.
- **Unacked injected (this session)** — your inbox, already shown, still
  awaiting `yoke messages acknowledge MESSAGE-ID`. Not the seat-awaiting
  count above. An overflow pointer means the body never injected: read
  `yoke messages get MESSAGE-ID` and ack; the row stays pending.
- **Idle holders** — probe and revive. A holder that stamped `--mode parked`
  declared its wait, one inside a long call is listed under **In flight**, and
  one the provider stopped under **Vendor-stopped sessions**; none of the
  three appears here. Verify the recorded state before dismissing an idle or
  stale row as an already-explained wait: read the holder's live `mode` and
  `quiet_reason` (`yoke sessions list --json`), not a memory of an earlier
  pass or a note already sitting in {SLUG} — knowing the reason, or having
  written it into the doc, is not the state change; only the mode stamp is.
  Once the blocker a parked holder named has actually cleared, send an
  item-addressed resume and confirm the holder's `mode` leaves `parked`
  before treating it as revived:

  ```text
  printf '%s' "RESUME PREFIX-N: <blocker> cleared, resume the routed leg" | yoke say --item PREFIX-N --stdin
  ```

  A starved holder is also burning down its stale clock,
  so read `stale_eligible_at` and `effective_stale_ttl_minutes` from its `yoke
  sessions list --json` row while triaging: at `stale_eligible_at` the reclaim
  sweep releases its claims and the item reads as untouched, so a holder
  near reclaim is revived before anything else in the pass.
- **In flight** — inside a watcher or merge landing wait: quiet because the command holds the turn, so nothing to do. For queue liveness use `yoke github merge-queue readiness PREFIX-N --json`; its named queue-entry state distinguishes consumed arming from a true clear. Past 45m it rejoins **Idle holders**.
- **Undelivered messages** — every envelope nobody has read yet, and the row
  names which of three kinds it is. **You owe a move** on *no delivery
  attempted* (the plane owed a wake and made none) and on *last attempt failed
  (reason)* (a refusal to fix; one reason repeating across a machine's rows is
  that relay). The reason is a code; the diagnosis behind it sits on the
  recipient's machine, so pull it with the row's own `evidence` clause before
  guessing — it round-trips through that machine's relay and is read-only:

  ```text
  yoke session-control evidence get --session {SESSION_ID}
  ```

  **Still on its way, so leave it** — *delivery attempt in flight*, *queued
  for the recipient's next hook*, and *recipient turn in flight* all end in
  *waiting*: none is a failure, and a wake would start a second turn.
  **Beyond reach** — *recipient session ended* or *terminated* means the
  envelope was addressed to a session that no longer exists and *no delivery
  route remains*; the row proposes nothing because nothing can be done to
  that session. Re-send the content to whoever should have it now. For the
  two you owe, use the wake or **Revive** bridge below.
- **Vendor-stopped sessions** — the model provider ended that worker's turn,
  not the worker. The end of the row says who moves next: an attempt and a
  time is the relay's, so leave it. A row naming you has no retry coming — an
  exhausted quota or rejected credentials (fix the account, not the session),
  or a spent budget, meaning every resume died the same way. Read the lane
  first: a worker that produced commits is worth resuming, one that never got
  a turn in is better reclaimed onto a fresh session; the same failure on
  every row of a machine is the provider or that client build.
- **Unregistered launches** — read which hand the row asks for. *native is
  live — bind it* means the process is up and only the binding is missing, so
  reconcile it onto the session the row names. *native is dead — reconcile,
  then retry* means the process exited; the row quotes the last line it wrote
  and its exit code, which is the reason to fix before retrying anything.
  `spawn_started` or `spawn_alive` in `native_launch_phase` belongs to the
  first process. Wait through `deadline_at`; reconcile refuses and retry
  reattaches without duplication. Otherwise use the commands below:
  `session_control.launch.list` reads `session_launches`;
  `session_control_launches` does not exist. It answers in two sets:
  `operational` carries every unfinished or actionable launch however old,
  so a stranded one is always in that first block rather than paged away,
  while `history` is the newest window of finished launches and
  `history_matched_count` names how many matched:

  ```text
  yoke session-control launch list --project {_project}
  yoke session-control launch reconcile {LAUNCH_ID} --json
  yoke session-control launch retry {LAUNCH_ID} --json
  ```
- **Abandoned launches** — the mandate reached a worker that never started:
  no claim, no message, no completed tool call, and its native is now gone.
  The item reads unclaimed rather than wrong, so nothing else in the pass will
  surface it. Read the quoted last line — a refusal that will repeat needs
  fixing before the work is restaffed — then staff the item again.
- **Landed without close-out** — merged already; only bookkeeping is owed.
  Message the named holder to re-enter `yoke merge item PREFIX-N`, which
  closes out from the recorded landing; on `no live holder`, restaff. Never
  redo the merge.
- **Dead waits** — a row naming an ended answerer, or an answerer whose own
  item is terminal, means no reply is coming: answer on the ended session's
  behalf, sending the asker the answer plus the current state of whatever
  it was waiting on. A `unresolved` row is an open question with a live
  answerer; it is context for the probe, not a finding to act on. Never
  send a bare `WAKE` to an idle holder without reading its row here — a
  wake alone parks it on the same question.

- **Plan limits** — informational table, one row per surface window (quota
  left, time-to-reset, headroom). Each row names the vendor-enforced meter and
  model scope — `weekly · all models` beside `weekly · Fable`. Cursor reports
  two monthly pools: `composer-*` and `cursor-grok-*` selections sit beside
  **Cursor Models**, while every other model sits beside **Other Models**.
  Claude and Codex likewise name the counter their vendor enforces. A row only
  answers for the models its own scope covers, so read a model against its own
  pool; only that pool's quota at zero is exhaustion, and unreadable is not
  empty ([`model-selection.md`](model-selection.md)). Compare headroom across
  every surface and window; under 100% can hit a wall before its reset, and
  approaching walls go to the operator. These numbers never gate a launch.
- **Capacity** — unlike plan limits, the line under each machine's launch
  balance does gate launches. `AT CAP, launches refuse` means the plane
  refuses there: wait for a landing to free a lane, raise
  `max_worker_lanes` in that machine's `~/.yoke/config.json` settings, or
  place the launch elsewhere with `--machine`. `capacity unreported` is an
  older relay, not a roomy machine.

