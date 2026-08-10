# Idea — File Budget Policy And Section

File Budget is a workflow policy axis independent of path claims. Read its
central effective value from
`workflows.item.get` → `result.effective_policies.file_budget` before
authoring this section. `required` enables it on the item,
`required_per_task` enables it on each generated task, and `optional` is
off. Never derive the effective value from raw pinned policies or posture.

When enabled, the File Budget section records the existing files the
implementation will touch, their current line counts, remaining headroom,
and explicit at-or-over-limit flags. It also carries a sibling-module plan
when any file is at or above 330 lines (the cap minus 20-line headroom).
When disabled, omit the section; the universal 350-line limit still applies through
`yoke_core.domain.file_line_check`.

**Edit targets only.** A file appears in `## File Budget` only if the
implementation will create, modify, or delete it. Context-only references
(files the spec quotes, files the reader needs to understand the
existing behavior, files named only to motivate the change) belong in
the Spec or Technical Plan section — not in the File Budget. The
readiness check classifies every backticked path under `## File Budget`
as an edit target and enforces `FILE_BUDGET_NOT_IN_CLAIM`: a context-only
mention triggers a false-positive remediation prompt. Keep the Budget
to the actual blast radius.

When enabled, the pre-handoff readiness check at idea exit and refine entry
validates this section through the registered readiness surface:

```bash
yoke readiness check PREFIX-N
```

It returns structured JSON with `verdict=pass|block|skipped`,
`classification`, `issues`, and non-blocking `advisories`.

## Required structure

```markdown
## File Budget

- Hard limit: 350 lines per authored file (enforced by `yoke_core.domain.file_line_check`).
- Design target: ≤300 lines per authored file.

### Current file-size pressure (verified `wc -l` on YYYY-MM-DD)

At-cap files (sibling required for any net-positive edit):
- `src/<package>/<file>.py` — current 350 lines; remaining headroom 0;
  at-or-over-limit: true; responsibility: `<single responsibility>`.

Near-design-target (small additions OK, but no logic growth):
- `src/<package>/<file>.py` — current 305 lines; remaining headroom 45;
  at-or-over-limit: false; responsibility: `<single responsibility>`.

Plenty of headroom (<200 lines):
- `src/<package>/<file>.py` — current 180 lines; remaining headroom 170;
  at-or-over-limit: false; responsibility: `<single responsibility>`.
```

The `wc -l` numbers MUST be current on the day the spec is authored.
Stale counts trip the readiness check.

## Sibling-module plan

When any file in the File Budget is at or above 330 lines, the spec
MUST declare an explicit sibling-module plan. The plan names the new
sibling file and which behavior moves into it:

```markdown
**Layer N — <description>:**

- `src/<package>/<existing>.py` — current 350 lines; remaining headroom 0;
  at-or-over-limit: true; no net add.
  Extract `<helper_name>` to a new sibling `<existing>_helper.py`.
- `src/<package>/<existing>_helper.py` — current 0 lines; remaining headroom
  350; at-or-over-limit: false; owns
  `<helper_name>` plus its private callees.
```

Without a sibling plan, refine has no architectural decision to validate
and the implementation falls into a recurring trap: attempting a
net-positive edit to a 350-line file fails `file_line_check` and forces
an emergency refactor mid-implementation.

## Project-relative path rule (cross-project work items)

All paths in `## File Budget` and in the `--paths` argument of the path-claim are **project-relative**. Validation resolves the local filesystem root from this machine's checkout mapping or explicit work/session context for the item's `project_id`; `path_targets.project_id` is the discriminator that lets identically-named paths coexist across projects.

When `project != yoke` (e.g. `project=external-webapp` checked out at `/Users/dev/external-webapp` on this machine), that checkout root is the **only valid root for File Budget enumeration and path-claim authoring**:

- Every File Budget entry is a path inside that checkout, written project-relative (e.g. `app/web/src/login/page.tsx` for external-webapp -- never `/Users/.../external-webapp/app/web/...`, never anything rooted in the Yoke tree).
- Any `Explore` / `Glob` / `Read` / `grep` dispatched to enumerate files for the File Budget MUST be scoped to the target project's local checkout. Do not search under a Yoke-side tree unless the target project is Yoke.
- The session-start orientation packet and `/yoke idea` project inference surface the resolved local checkout when one exists (see [infer-and-create.md](infer-and-create.md)); absence of a local checkout is a setup problem, not permission to author paths from another repo.

## File Budget vs path-claim consistency

Parity is conditional, not universal. Only when both effective axes are
enabled must every File Budget path appear in the path claim's declared
coverage and vice versa. The readiness check then enforces the intersection:

- `FILE_BUDGET_NOT_IN_CLAIM` — File Budget names a file the claim does
  not declare. Widen the claim or remove the file from the Budget if
  it is referenced as context, not as an edit target.
- `CLAIM_NOT_IN_FILE_BUDGET` — claim declares a file the Budget does
  not name. Add the file to the Budget or narrow the claim if it is
  no longer touched.

When File Budget is off and path claims are on, derive claim paths from the
execution document, instruction, or investigated spec scope. When File Budget
is on and path claims are off, the budget remains sizing and conflict evidence
and no claim is registered. When both are off, neither artifact is required.
