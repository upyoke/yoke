# Act on every fleet finding

Read whole report before action; live row/evidence wins over remembered wait
or plan note. Nothing acknowledged is automatically completed.

- **Available work**: staff scoped runnable unclaimed work; ! marks staffing
  age threshold, unmarked is still available. Recheck holder before launch.
- **Unattended linked work**: take/arrange exact owning project+document seat
  named by row before staffing; project seat does not cover another doc link.
- **Steering messages awaiting a seat**: acquire scope for unacknowledged parked
  or ended-seat mail; acknowledged receipts never inherit. Plan unfinished actions.
- **Unacked injected (this session)**: receipt already shown, including oversized
  stub. Read yoke messages get MESSAGE-ID fully and acknowledge; separate from
  seat-awaiting mail.
- **Idle holders**: process running→message; exited→message resumes transcript;
  resuming now→let start. `--mode parked` declared its wait; in-flight,
  vendor-stopped and stranded are separate rows. Read live mode/quiet_reason with
  yoke sessions list --json, not remembered reason. When actual blocker clears,
  item-address resume and confirm mode leaves parked. Active work claims protect
  holders from age-based reclaim; no stale TTL countdown releases a live lane.
  Read reported effective_stale_ttl_minutes/reclaim evidence only for the actual
  applicable session state; never diagnose claim loss from age alone.
- **In flight**: watcher/landing wait holds turn; quiet is expected. Queue
  readiness names consumed arming vs clear; act when report reclassifies it,
  not a manually invented deadline.
- **Undelivered messages**: no attempt or failed last attempt means you owe
  recovery. Pull row's read-only machine evidence before diagnosing repeated
  relay code. Attempt moving, queued next hook or recipient turn in flight
  means waiting: no second wake. Ended/terminated recipient has no route:
  cancel named message then re-address content to current recipient; a successor
  cannot acknowledge old session mail.
- **Vendor-stopped sessions**: row with attempt/time belongs to relay retry;
  leave it. Row naming seat needs account repair or deliberate restaff after
  exhausted/spent resume budget. Read lane commits first: produced work merits
  recovery, never-started work can restaff. Repeated machine signature needs
  evidence-led provider/client diagnosis.
- **Stranded sessions**: confirmed published meter empty, credentials rejected
  or model unavailable cannot resume; don't wake. Changed preferred default,
  unreadable meter or launch still within registration deadline is not stranded.
  meter_exhausted names relaunch with headroom; resumed-died can report
  blocked-meter-exhausted. Preserve exact recovery evidence.
- **Unregistered launches**: native live→bind; native dead→read quoted last line/
  exit, reconcile then retry after repair. spawn_started/spawn_alive owns first
  process until deadline_at; reconciliation refuses/native retry reattaches,
  never duplicate. session_control.launch.list reads session_launches.
  session_control_launches does not exist. Operational includes actionable
  launches regardless of age; history is bounded finished window with count.
- **Abandoned launches**: no claim/message/completed tool call and native gone;
  read last refusal before restaff, so failure does not repeat invisibly.
- **Landed without close-out**: message holder to rerun yoke merge item PREFIX-N;
  no live holder means restaff. Reuse landing, never merge twice.
- **Dead waits**: ended answerer/terminal answering item means no reply is coming;
  answer on the ended session's behalf with the answer and the current state of
  whatever it was waiting on. An `unresolved` row is an open question with a live
  answerer. Read it before probing; a wake alone parks it on the same question.

```text
yoke sessions list --json
yoke session-control evidence get --session SESSION-ID
yoke session-control session wake --item PREFIX-N --prompt "Resume: the named blocker cleared" --json
yoke messages cancel MESSAGE-ID
yoke session-control launch list --project {_project}
yoke session-control launch reconcile {LAUNCH_ID} --json
yoke session-control launch retry {LAUNCH_ID} --json
yoke github merge-queue readiness PREFIX-N --json
```

Wake only for an owed stopped-session recovery. wake_in_flight preserves moving
receipt; superseded unattempted wake reports RELEASED after grace. Desktop
operator_wake_required is not a native retry; message then operator prompt.
Do not wake a confirmed exhausted model; no direct native resume bridge.

**Plan limits** are informational scoped vendor pools, not launch gates.
Read model against its own pool; Cursor composer/grok selections use Cursor
Models, others Other Models. Claude/Codex likewise name enforced scope.
Only that pool at zero is exhausted. Unreadable is not empty: stale_credential
needs sign-in; http_429/failed probe retries refresh and proves nothing about
launchability. Do not route away on unreadable alone. Compare all windows'
quota/headroom/reset and raise approaching walls to operator. See model-selection.

**Capacity** does gate launch. AT CAP requires landing/free lane, operator
max_worker_lanes setting, or --machine with room. capacity unreported is an
older relay, never proof of room. Read actual machine memory/capacity receipt.
