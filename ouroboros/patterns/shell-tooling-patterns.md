# Shell & Tooling Patterns

Cross-link back from the [pattern catalog](../patterns.md) for the full Ouroboros index.

## P-16: zsh != history expansion corrupts SQL operators

**First observed:** 2026-03-01 (T1 conductor, SINAI sprint)
**Promoted:** 2026-03-01
**Occurrences:** 8+ entries across all 5 conductor tracks
**Status:** Resolved — hook now blocks both `!=` and `\!=`, enforcing `<>` as the only safe not-equal operator.

zsh histexpand (active even in the non-interactive Bash tool shell) converts `!=` to `\!=` in double-quoted strings. The backslash is NOT stripped before the SQL reaches the database CLI, causing token errors. The earlier YOK-280 theory (that zsh strips `\!` before the CLI sees it) was disproven empirically: both `!=` and `\!=` arrive as `\!=`.

**Action:** The DB-command guard (today `lint_db_cmd`; legacy stable id `lint-sqlite-cmd`) blocks both forms with a clear message directing to `<>`. All SKILL.md SQL queries updated to use `<>`. The `!=` operator is **permanently unusable** in this environment — `<>` is the only safe not-equal operator. Also fixed pre-existing test bugs: `assert_allows` was masking 9 failures due to multi-line deny output.

---

## P-17: Stale lock directories block board rebuilds in parallel sessions

**First observed:** 2026-03-01 (T3 conductor)
**Promoted:** 2026-03-01
**Occurrences:** 5+ entries across T1, T3, T4 conductor sessions
**Status:** Active — no stale lock detection implemented

`BOARD.md.lock` goes stale from parallel sessions or rapid sequential rebuilds, requiring manual `rmdir` intervention. With 5 parallel conductor sessions, lock contention is frequent.

**Action:** lock-helper.sh should detect stale locks (check PID liveness or lock age) and auto-clean. Directory-based lock requires `rmdir` not `rm -f`.

---

## P-18: Test environment mock setups missing new dependencies

**First observed:** 2026-02-28 (YOK-196 T2 conductor)
**Promoted:** 2026-03-01
**Occurrences:** 3+ entries (doctor health-check suite missing item-db.sh, test-dry-run.sh missing item-db.sh, test-body-sync.sh missing sync-helper.sh)
**Status:** Active — no automated dependency check

When a script gains a new `source` dependency (e.g., `item-db.sh`), ALL test environments that mock that script's directory must be updated to include the new dependency. The fix is always trivial (add one `cp` line) but discovery costs debugging time.

**Action:** Convention: after adding a new source/dependency to any script, grep all test scripts for `cp.*scripts/` and add the new file. Shared test-helpers.sh (YOK-240) centralizes setup but doesn't solve the dependency enumeration problem.

---

## P-19: YOKE_DRY_RUN=1 causes false test failures

**First observed:** 2026-02-28 (YOK-196 T2 conductor)
**Promoted:** 2026-03-01
**Occurrences:** 2+ entries
**Status:** Addressed — documented in AGENTS.md Testing section

Test suites use mock `gh` scripts that log calls. YOKE_DRY_RUN=1 causes scripts to skip `gh` calls entirely, so mocks never fire and log files are empty. Tests checking those logs all fail.

**Action:** AGENTS.md Testing section: "Never set YOKE_DRY_RUN=1 when running test suites." Tests manage their own isolation via mock `gh` commands.
