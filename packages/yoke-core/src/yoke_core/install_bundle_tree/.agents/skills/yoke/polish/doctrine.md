# Polish — Doctrine

The result must work end to end through the UI, CLI or workflow users encounter:
wiring, defaults, errors, help and configuration documentation all count.
Think top-down from the item's purpose and bottom-up from each diff, before and
after the checklist. Verify named spec facts against source; fix or flag gaps
a reasonable operator would expect even when the AC omitted them.

Code and documentation describe the present. Keep non-obvious WHY comments;
remove historical amendments, completed TODOs and zero-consumer compatibility
shims, aliases and reexports. Delete orphaned helpers, obsolete fixtures,
dead tests, config, flags and docs, unreachable branches and impossible-state or
imaginary fallbacks. **Permanent ordered migration modules remain:** an
installation that never received one still needs it. Read the governed
database contract before migration changes; remove unused compatibility code
only outside that history and after verifying no live consumers.

Describe review failures as systemic causes—missing contracts, paths or context,
ambiguous specs, truncation—not blame. Fix the code and record prevention.
For unclear failures inspect bounded telemetry before guessing:
```bash
yoke events tail --limit 20
yoke events anomalies --since "4 hours ago"
yoke events query --item "$ITEM_REF"
```

**Codebase-reader naming:** every new/renamed file, directory, symbol, test,
command, event, setting, heading and comment must explain current purpose,
mechanics or domain role without its planning artifact. Rewrite work-item,
plan, phase, task, AC/FR, branch or batch provenance unless it is actual runtime
domain language. Clear names and descriptive commits are the maintainer handoff;
do not restate the implementation transcript.

The shared Simplify doctrine in AGENTS.md governs reuse, quality, efficiency
and future-concept pull-forward. Reuse existing surfaces/constants/types;
keep the smallest complete request shape; justify infrastructure against what
exists. Surfaces concerning actors, sessions, leases, claims, approvals,
evidence, journals, locks or shared-state coordination need an end-state v0 or
an explicit deletion/absorption target. Retain migration history while removing
unnecessary indirection and redundant computation.
