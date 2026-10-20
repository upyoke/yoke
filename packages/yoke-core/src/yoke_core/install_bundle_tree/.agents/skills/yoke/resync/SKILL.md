---
name: resync
description: Detect and repair drift between local backlog items and their GitHub issues. Default mode is detect-only (read-only); use --fix for auto-repair.
argument-hint: "[--fix]"
---

# /yoke resync [--fix]

```text
yoke resync --fix
```

Omit `--fix` to only detect. Show each mismatch and each repair actually made;
never claim an unperformed repair.
