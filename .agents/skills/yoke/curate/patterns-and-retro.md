# Curate Phase: Promote Patterns And Print The Retrospective

This phase owns recurring-pattern detection, pattern promotion, and the final retrospective output for `/yoke curate`.

## 7. Scan For Recurring Patterns

Query both unreviewed and recently archived entries for pattern detection:

```bash
yoke ouroboros entry list
```

Also read `ouroboros/patterns.md`.

Look for observations that appear three or more times by semantic similarity. Consider:
- Same category of problem reported by different agents
- Same improvement suggestion from different contexts
- Same class of issue appearing repeatedly

For each recurring pattern found, present:

```text
Recurring pattern detected: {description}
Observed {N} times across {agent list}
First observed: {earliest timestamp}

Promotion options:
1. Create a new rule in .claude/rules/
2. Create a code change ticket
3. Ignore
```

For options 1 or 2, record the promoted pattern in `ouroboros/patterns.md`:

```text
### {Pattern description}
- First observed: {date}
- Promoted: {today's date}
- Observations: {N}
- Action: {rule created | ticket filed: YOK-N}
```

## 8. Display The Ouroboros Retrospective

Show a summary at the end:

```text
# Ouroboros Retrospective

## Entries Processed
- Total entries examined: {N}
- By category: {N} problems, {N} friction, {N} ideas, {N} cross-critiques
- By agent: {agent: count, ...}

## Clusters
- Clusters formed: {N}
- Tickets filed: {N} ({YOK-N, YOK-N, ...})
- Entries skipped: {N}
- Entries deferred: {N}
- Clusters flagged as likely resolved: {N}

## Archiving
- Entries archived: {N}
- Entries remaining (unreviewed): {N}

## Patterns
- Recurring patterns found: {N}
- Patterns promoted: {N}
```
