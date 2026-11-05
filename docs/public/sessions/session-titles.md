# Chat titles and session labels

Session mentions show the native chat title, surface, project, current item
claims (or the most recently released item), and activity age. An unnamed
launched chat uses its assigned item ref and title. Labels resolve when read,
so later renames and claim changes appear in existing notices and messages.
UUIDs remain in commands and secondary session details.

Session cards retain their usual fields. Hover or tap their identity header
to reveal the title. Dashboard search matches chat titles.

A prompt or Stop hook observes the name on the machine running the harness:

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
leasing the job. Claude receives `--name`; Codex receives `thread/name/set`.
Cursor has no worker naming surface.

When a desktop wake notice names a chat, open that chat and type anything.
Its next hook delivers the waiting message; Yoke leaves that wake to you
because a native resume would fork the transcript you are reading.
