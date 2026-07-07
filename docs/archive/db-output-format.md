# Yoke DB Output Format

This document standardizes shell-facing output from Yoke DB queries.

## Primary Convention

Pipe-delimited output (`-separator '|'`) is the default convention for shell parsing.

Use it for compact row-oriented data where each field is known and ordered.

## Escaping Rules

### Safe fields (no escaping required)

These fields are expected to be single-line values without pipe separators:

- `id`
- `status`
- `priority`
- `type`
- `sprint`
- `track`
- `track_seq`
- `frozen`
- `worktree`

### Unsafe fields (must be escaped or normalized)

These fields may contain pipes or newlines and must not be emitted raw in pipe-delimited rows:

- `body`
- `title`
- `dependencies`
- Free-text notes/comments fields

For multiline body-like fields, normalize newlines in SQL:

```sql
REPLACE(body, CHAR(10), '\n')
```

For title-like fields that may contain literal `|`, normalize to a visible alternate delimiter:

```sql
REPLACE(title, '|', '∣')
```

## Helper Pattern: `_safe_body_select()`

When writing DB wrappers, use a consistent safe-select pattern for body fields:

```sql
SELECT
  id,
  REPLACE(COALESCE(body, ''), CHAR(10), '\n') AS body_safe
FROM items;
```

Equivalent inline pattern:

```sql
REPLACE(COALESCE(body, ''), CHAR(10), '\n')
```

## Standard Parsing Pattern

Use `IFS='|' read -r ...` and expect positional fields.

```sh
sh .claude/skills/yoke/scripts/yoke-db.sh query -separator '|' \
  "SELECT id, status, REPLACE(COALESCE(body, ''), CHAR(10), '\n') FROM items" \
| while IFS='|' read -r _id _status _body; do
    # Optional: rehydrate escaped newlines for display-only usage
    _body_display=$(printf '%s' "$_body" | sed 's/\\n/\n/g')
    :
  done
```

## Recommended Usage

- Use pipe-delimited output for metadata rows and control-flow decisions.
- For rich free-text processing, prefer two-step access:
  1. list IDs/metadata via pipe rows
  2. fetch full bodies with `yoke-db.sh items get N body`

## Future Direction

JSON output mode is planned for callers that need structured nested data or lossless free-text transport.
