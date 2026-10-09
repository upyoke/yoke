# Idea — File Budget

Read central effective file_budget independently from path_claims:
required item, required_per_task generated tasks, optional off.
Universal350 authored lines holds in every posture; <=300 is design target.

Budget rows are only actual create/edit/delete files, not context references.
Only physical paths occupy list-item backticks; symbols/events/commands stay
in prose. Use the target project's registered checkout exclusively and store
project-relative paths, never absolute paths or another repo's tree.
Missing target checkout is setup recovery, not permission to borrow one.

## Structure and current counts

Known shape: literal every file, one responsibility, today's verified count,
remaining headroom350-current (negative retained), at-or-over-limit true
when count>=350. New files start0:
```markdown
## File Budget

- Hard limit: 350 authored lines; design target <=300.
- `src/consumer.py` — current 120 lines; remaining headroom 230; at-or-over-limit: false; responsibility: validate incoming requests.
- `src/decoder.py` — current 0 lines; remaining headroom 350; at-or-over-limit: false; responsibility: decode the supported payload.
```

At>=330 (20-line cap headroom), specify the sibling path and exactly which
behavior/private callees move. At-cap net-positive edits require extraction
and no net add to existing file. At300+ identify pressure; small additions
within remaining headroom do not authorize unbounded logic growth.
Unknown implementation shape uses UNRESOLVED and forces Refine resolution;
honest no-authored-growth uses N/A/reason, revised before discovered coding.

## Independent parity and validation

Both axes enabled: every budget path appears in declared claim coverage and
vice versa. FILE_BUDGET_NOT_IN_CLAIM widens or removes a genuinely context-only
row; CLAIM_NOT_IN_FILE_BUDGET adds the required row or narrows an actually
untouched path. Never remove a required file because another holder claimed it.
Claims alone derive complete execution scope; budget alone stays sizing/conflict
evidence; neither creates neither.

```bash
yoke readiness check PREFIX-N
```

Inspect verdict/classification/issues/advisories. Unavailable is unperformed,
not skipped or passing; final closure owns the full enumeration.
