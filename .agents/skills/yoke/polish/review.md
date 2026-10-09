# Polish — Review The Implementation

## 6. Review

For every registered lane inspect status, committed diff and dirty changes:
```bash
git -C "<absolute-lane-path>" status --short
git -C "<absolute-lane-path>" diff --stat main...HEAD
git -C "<absolute-lane-path>" diff --name-only main...HEAD
git -C "<absolute-lane-path>" diff main...HEAD
git -C "<absolute-lane-path>" diff
git -C "<absolute-lane-path>" diff --cached
```

If there is no committed diff, the dirty diff still needs review. Produce a
section for each lane before parent synthesis; any lane's finishing gap blocks
the parent. Incorporate **all** survey findings. Resolve actual overlap through
verified adaptation, dependency/claim reconciliation, absorption or an authorized
scope decision; do not silently omit required files.

Search beyond the diff/spec's file list for every changed signature, rename or
removal: callers, imports, docs, configs, scripts and tests. Use real `rg`
discovery and verify zero retired-identifier residue. Inspect corresponding
tests for each modified module/script and supply extracted-helper dependencies
in **all** caller test environments. For unclear failures inspect bounded
events before guessing.

Measure authored files and prompt readability. **350 authored lines is the
universal hard limit**, independent of File Budget or stricter project policy.
Run `yoke check file-line --base main`; split oversized authored files.
Truncation and unreadable dispatch surfaces are first-class review findings.

Review every AC and peripheral obligation, not only the core:
- Correctness, end-to-end reachability, defaults, errors, empty/boundary inputs,
  validation, safety/injection risks, conventions and integration.
- Verify named files/functions/columns/lines against actual source. Close clear
  implied requirements; flag material scope expansion for the operator.
- **Codebase-reader naming:** surfaces explain current function without a
  planning artifact. Review names across files, tests, docs, settings and events.
- Full blast radius and zero residue after rename/removal; dead helpers,
  imports, variables, config/flags, zero-consumer shims/reexports, unreachable
  branches and imaginary fallbacks.
- Current comments/docstrings/help/README/docs; no historical amendment or
  completed TODO. Review migration necessity against real live data, but
  **never delete permanent ordered migration modules**, even for empty data.
- Reuse and efficiency: avoid redundant queries/reads, pass-through wrappers,
  unnecessary loops/pipelines and frameworks for one use. Prefer clear direct
  behavior, not compressed cleverness.

Review tests for each changed behavior/AC, behavioral assertions, independent
temporary state, and complete co-modification. Remove tests for retired behavior
outside permanent migration coverage; update stale names/comments. Relevant
coverage matters more than mirroring implementation.

Emit one structured review with:
- **Implementation Status:** every AC covered/partial/missing with evidence.
- **Lane Coverage:** actual branch/path and clean/needs-fixes evidence.
- **Issues Found:** severity, concrete description and file:line.
- **Finishing Fixes Planned:** change and purpose.

Proceed to [fixes.md](fixes.md) with unresolved findings.
