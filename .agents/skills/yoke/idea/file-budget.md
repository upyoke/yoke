# Idea — File Budget

One row per file created, edited or deleted, project-relative:

```markdown
## File Budget
- `src/consumer.py` — current 120 lines; remaining headroom 230; at-or-over-limit: false; responsibility: validate requests.
```

Every row carries all three sizing fields; readiness refuses a row without them. A new file is `current 0 lines; remaining headroom 350; at-or-over-limit: false`. At 330+ lines name the extraction sibling.
