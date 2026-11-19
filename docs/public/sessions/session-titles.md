# Chat titles and session labels

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Sessions](index.md) > Chat titles and session labels
<!-- /yoke:breadcrumbs -->

Session mentions show the native chat title, surface, project, current item
claims (or the most recently released item), and last tool age. An unnamed
launched chat uses its assigned item ref and title. Labels resolve when read,
so later renames and claim changes appear in existing notices and messages.
Labels say `last tool Nm ago` using only the last tool call. Heartbeats never
refresh this age, including after a process exits; without a tool timestamp,
the label omits the age.
UUIDs remain in commands and secondary session details.

Session cards keep the harness name in the header. A worker with its generated
launch title and a current claim on that item shows the item once, under
Currently held. A distinct native chat title can appear on its own line.
Cards with a steering claim and cards with item-derived fallback titles keep
those titles in Session details. Hover over or tap the Session details button
to see the title and state details. Search matches titles.

A session start, prompt or Stop hook observes the name on the machine running
the harness. Desktop and CLI surfaces use their harness family's title reader:

- Claude reads the latest `custom-title` record in its transcript tail. If
  no title has been observed, it scans the file forward once.
- Codex reads the latest matching `thread_name` from `session_index.jsonl`
  under `CODEX_HOME` (default `~/.codex`), then `threads.name` in
  `state_5.sqlite`. The session id is the thread id; the first prompt is
  never used as a name.
- Cursor desktop reads the composer name from `state.vscdb`; Cursor CLI
  reads the chat name from its `store.db` metadata. `New Agent` is unnamed.

Only a changed title travels to the control plane as a client fact; chat
content stays on the machine. Unnamed headless chats use the item label.

Launches store their assignment in nullable `session_launches.item_id`.
The relay derives the worker name from the current item ref and title when
leasing the job. Claude receives `--name`. Codex desktop sets the native title
before the first turn. Codex CLI sets it on the exact thread after `codex exec`
exits and flushes its first turn. A naming failure appears in the launch's
native capture. Cursor has no worker naming surface.

When a desktop wake notice names a chat, open that chat and type anything.
Its next hook delivers the waiting message; Yoke leaves that wake to you
because a native resume would fork the transcript you are reading.
