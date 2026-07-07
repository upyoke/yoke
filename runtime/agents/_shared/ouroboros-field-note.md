# Ouroboros Field-Note Channel

Canonical long-form reference for the field-note channel. Auto-generated from `runtime/api/domain/field_note_text.py` constants; do not edit the block between markers by hand.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.

Copy-paste recipe:

    yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'

## Failure modes

### Recipe missing (`--kind new`)

**When to fire:** Agent needed a workflow with no existing recipe coverage — no skill, packet, or --help surface taught it.

**Example evidence:** No recipe covers narrowing a path claim by drop-paths; had to grep service_client for the flag.

### No help info accessible (`--kind new`)

**When to fire:** `--help` returns nothing, a stub, or no body — the producer cannot self-orient without leaving the CLI.

**Example evidence:** `yoke claims path register --help` returns no body, just usage line.

### Recipe wrong / needs tweak (`--kind failed`)

**When to fire:** Recipe was taught but produced the wrong result when followed literally (wrong flag, wrong arg order, wrong subcommand).

**Example evidence:** R-CL-03 path-claim-narrow taught --remove; actual flag is --drop-paths.

### Help info wrong (`--kind failed`)

**When to fire:** `--help` example doesn't match real behavior — running the example verbatim exits non-zero or returns the wrong shape.

**Example evidence:** `yoke items get --help` example shows `--field body`; real field name is `body` without the flag.

### Lint or guard blocked something that should be allowed (`--kind failed`)

**When to fire:** A lint or guardrail refused a legitimate operation, forcing a workaround that the rule did not intend to require.

**Example evidence:** lint_session_cwd denied a write under an OS-temp scratch path; free-path allowlist should cover /tmp.

### Conflicting recipes (`--kind unclear`)

**When to fire:** Two teaching surfaces give contradictory forms for the same operation.

**Example evidence:** skill body teaches `db_router items update`; AGENTS.md teaches `items.structured_field.replace`. Both fire on the same surface.

### Block or error message could be more useful (`--kind unclear`)

**When to fire:** A block or error message left out concrete remediation context — the holding session, the missing path, the next command to run.

**Example evidence:** path-claim-register exited with 'overlap detected' — did not name the holding session, item, or paths in the overlap set.

### Stale doc reference noticed during unrelated work (`--kind observation`)

**When to fire:** Reading a doc, skill, or packet during unrelated work surfaced a stale or wrong reference. Not in current scope, not worth a ticket.

**Example evidence:** docs/lifecycle.md still references `polish-implementation`; the live status name is `polishing-implementation`.

### Orphan row or stale state noticed during unrelated work (`--kind observation`)

**When to fire:** Stumbled on durable state (DB row, file, lease) that looks stale but is not blocking the current item. Capture for later cleanup.

**Example evidence:** Saw a `work_claims` row with `released_at IS NULL` whose owning session ended 3 days ago; no live session is operating on it.

### Surprising behavior in an unrelated surface (`--kind observation`)

**When to fire:** An unrelated surface behaved in a way that was surprising but did not block current work. Not worth diagnosing today.

**Example evidence:** `yoke board` rendered an item with empty title where the DB row has a non-empty title column — render path may be stripping it.

Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->
