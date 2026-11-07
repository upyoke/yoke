---
name: resync
description: "Detect, and with --fix repair, drift between items and their GitHub issues."
argument-hint: "[--fix]"
---

# /yoke resync [--fix]

```text
yoke resync --fix
```

Omit `--fix` to only detect. Show each mismatch and each repair actually made;
never claim an unperformed repair.
