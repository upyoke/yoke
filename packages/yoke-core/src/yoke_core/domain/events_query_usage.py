"""CLI usage text for event query commands."""

LIST_USAGE = """\
Usage: events list [filter flags...] [--limit N]
       events list --help

Filter flags (combine with AND across distinct columns):
  --source-type, --session-id (or --session), --event-kind, --event-name,
  --agent, --service, --actor-id, --trace-id, --project,
  --item-id (or --item), --tool-use-id, --turn-id, --hook-event-name VALUE
  --min-severity DEBUG|INFO|STATUS|WARN|ERROR|FATAL
  --since VALUE
  --until VALUE
  --current-episode  (requires --session-id; bounds to latest session boundary)
  --limit N

--since / --until accept ISO-8601 or `N (second|minute|hour|day|week)[s] ago`
resolved against current UTC; unparseable values fail closed.

Failure-shaped presets:
  --failed-only            Narrow to failed-class event_outcome values.
  --friction-summary       Group failed-class outcomes by session_id.

`--item` accepts PREFIX-N refs, or bare N with project context.
Unknown flags are rejected to prevent silent
unfiltered output.
"""
