# Machine-local evidence

A relay diagnostic, a watcher capture, and the relay's own service log are written to the machine that produced them and to nowhere else. That is right — they can hold native output, and shipping every machine's logs into the control plane would be both a privacy problem and a storage one. It also means a seat on another machine could see *that* a launch or a wake failed and never see *why*, which is the half an operator actually needs. Four steering waits were abandoned by hand in one night over failures whose whole diagnosis sat unread on the machine that produced it.

`session_control.evidence.get` closes that without moving anything. The control plane holds the request, hands it to the one relay whose machine wrote the files, and stores the bounded answer that comes back.

```text
yoke session-control evidence get --session SESSION-ID [--kind relay|watcher|diagnostic] [--file NAME] [--evidence-id ND-REF] [--tail N] [--wait-seconds N]
```

The answer is a listing of what that machine holds for the session plus the tail of one of those files. `--help` carries the flag matrix; the facts that shape it are below.

## What the machine can find, and how

Three kinds, and they are keyed differently on disk:

- **`watcher`** — captures under the session's own scratch subtree, keyed by session id. The project segment above `sessions/` is resolved from the writing process's configuration, which the relay does not share, so the listing walks every project segment; a session id is unique across them. Entries are named `<run>/<file>` so two runs of one session never collide.
- **`relay`** — the relay service's own `relay.stdout.log` and `relay.stderr.log`. Machine-scoped rather than session-scoped: they are what the relay itself said while it was failing to serve that session.
- **`diagnostic`** — the private `nd-` captures a native failure left behind. These are **not** keyed by session on disk, so the machine cannot answer "what do you hold for this session" about them on its own. The control plane can: every reference was reported to it by the attempt that produced it, and those attempts name the session (`session_message_attempts.target_session_id`, and `session_launch_attempts` joined through `session_launches.registered_session_id` / `native_session_id`). So the job carries the explicit reference list, resolved control-plane-side, and the relay reads only those.

Selection order: `--evidence-id` names one exact `nd-` reference — what the fleet report links; `--file` names one entry from a previous listing; with neither, the newest file of the requested `--kind` is read. `--kind` alone narrows the listing.

## Bounds

The read is read-only and bounded twice. `--tail` caps lines (default 200, max 2000) and the relay re-caps its answer at 64 KiB whatever line count it was handed, so one runaway line cannot become an unbounded control-plane write. A diagnostic goes back through its own owner-and-permission-checked reader, so the private-capture rules that store it also govern reading it back; symlinks and files owned by another OS user are never opened.

## Table: `session_evidence_fetches`

One row per request. It is the rendezvous between the seat that asked and the machine that answers, and it is disposable operational state — omittable from portable archives, like the relay and attempt tables it sits beside.

| Column | Meaning |
|---|---|
| `fetch_id` | The request's identity. |
| `target_session_id`, `project_id`, `machine_id` | Whose files, whose authority, and which relay may lease it. `machine_id` comes from the target session's own row. |
| `kind`, `file_name`, `diagnostic_ref`, `tail_lines` | The exact bounded question. |
| `state` | `pending` → `leased` → `succeeded` / `failed`, or `expired`. |
| `requested_at`, `requested_by_actor_id`, `requested_by_session_id` | Who asked and when. |
| `lease_id`, `lease_expires_at` | The owning relay's lease; an expired lease returns the row to `pending`. |
| `completed_at`, `result_code` | `read`, `no_files`, `not_found`, or `unreadable`. The first two are answers, not failures. |
| `files`, `selected_file`, `content`, `content_bytes`, `truncated` | What came back. |

## Timing, retries, and the relay job

The request rides the existing machine-keyed relay job routing as job kind `evidence`, alongside `launch`, `wake`, and `terminate`. It is leased ahead of launches and wakes: a seat's dispatch is blocked on it and it costs the machine one file tail, so it goes in front of the minutes-long native work rather than behind it. A relay sitting in its long poll picks one up within a second.

The calling dispatch waits `--wait-seconds` (default 10, max 30) and then returns the row as it stands. A pending answer carries `recovery`, which is the same command again — retrying **joins the request in flight** rather than queueing a second one, because a request is deduplicated on its exact shape while it is non-terminal. A request no relay leased within five minutes is expired rather than served long after the person who asked walked away.

Only the machine named on the row may lease it, and only the lease it was granted may report it. A report from another relay, or with a stale lease, is refused as `lease_mismatch`.

## Where the link appears

The fleet report's [undelivered-message and unregistered-launch rows](steering-fleet-report.md) end with an `evidence` clause naming `yoke session-control evidence get --session <id>`, carrying `--evidence-id` when that row's attempt recorded a diagnostic reference. Both rows render it through one contract helper (`evidence_pull_suffix`), so a row naming a failure on another machine always names the read that brings it here.

The machine-local route still exists and still works: `yoke relay diagnostic <nd-ref>` reads a capture directly, which is what an operator standing on that machine wants and what still answers when the relay is down.
