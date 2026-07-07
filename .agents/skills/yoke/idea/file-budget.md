# Idea — File Budget Section

The File Budget section of every spec records the existing files the
implementation will touch, their current line counts, and an explicit
sibling-module plan when any file is at or above 330 lines (the cap
minus 20-line headroom).

**Edit targets only.** A file appears in `## File Budget` only if the
implementation will create, modify, or delete it. Context-only references
(files the spec quotes, files the reader needs to understand the
existing behavior, files named only to motivate the change) belong in
the Spec or Technical Plan section — not in the File Budget. The
readiness check classifies every backticked path under `## File Budget`
as an edit target and enforces `FILE_BUDGET_NOT_IN_CLAIM`: a context-only
mention triggers a false-positive remediation prompt. Keep the Budget
to the actual blast radius.

The pre-handoff readiness check at idea exit and refine entry validates
this section through the registered readiness surface:

```bash
yoke readiness check <item_id>
```

It returns structured JSON with `verdict=pass|block|skipped`,
`classification`, `issues`, and non-blocking `advisories`.

## Required structure

```markdown
## File Budget

- Hard limit: 350 lines per authored file (enforced by `runtime/api/domain/file_line_check.py`).
- Design target: ≤300 lines per authored file.

### Current file-size pressure (verified `wc -l` on YYYY-MM-DD)

At-cap files (zero net headroom — sibling required for any net-positive edit):
- `runtime/api/domain/<file>.py` = 350

Near-design-target (small additions OK, but no logic growth):
- `runtime/api/domain/<file>.py` = 305

Plenty of headroom (<200 lines):
- `runtime/api/domain/<file>.py` = 180
```

The `wc -l` numbers MUST be current on the day the spec is authored.
Stale counts trip the readiness check.

## Sibling-module plan

When any file in the File Budget is at or above 330 lines, the spec
MUST declare an explicit sibling-module plan. The plan names the new
sibling file and which behavior moves into it:

```markdown
**Layer N — <description>:**

- `runtime/api/domain/<existing>.py` (350 lines, AT CAP) — no net add.
  Extract `<helper_name>` to a new sibling `<existing>_helper.py`.
- `runtime/api/domain/<existing>_helper.py` (new, ≤180 lines) — owns
  `<helper_name>` plus its private callees.
```

Without a sibling plan, refine has no architectural decision to validate
and the implementation falls into a recurring trap: attempting a
net-positive edit to a 350-line file fails `file_line_check` and forces
an emergency refactor mid-implementation.

## Project-relative path rule (cross-project tickets)

All paths in `## File Budget` and in the `--paths` argument of the path-claim are **project-relative**. Validation resolves the local filesystem root from this machine's checkout mapping or explicit work/session context for the item's `project_id`; `path_targets.project_id` is the discriminator that lets identically-named paths coexist across projects.

When `project != yoke` (e.g. `project=buzz` checked out at `/Users/dev/buzz` on this machine), that checkout root is the **only valid root for File Budget enumeration and path-claim authoring**:

- Every File Budget entry is a path inside that checkout, written project-relative (e.g. `app/web/src/login/page.tsx` for buzz -- never `/Users/.../buzz/app/web/...`, never anything rooted in the Yoke tree).
- Any `Explore` / `Glob` / `Read` / `grep` dispatched to enumerate files for the File Budget MUST be scoped to the target project's local checkout. Do not search under a Yoke-side tree unless the target project is Yoke.
- The session-start orientation packet and `/yoke idea` project inference surface the resolved local checkout when one exists (see [infer-and-create.md](infer-and-create.md)); absence of a local checkout is a setup problem, not permission to author paths from another repo.

## File Budget vs path-claim consistency

Every file in the File Budget MUST appear in the item's path-claim
declared coverage, and vice versa. The readiness check enforces the
intersection:

- `FILE_BUDGET_NOT_IN_CLAIM` — File Budget names a file the claim does
  not declare. Widen the claim or remove the file from the Budget if
  it is referenced as context, not as an edit target.
- `CLAIM_NOT_IN_FILE_BUDGET` — claim declares a file the Budget does
  not name. Add the file to the Budget or narrow the claim if it is
  no longer touched.

The mismatch class is a recurring one: under-enumerated File Budget,
claim copies that under-enumeration, refine has to surface the gap
manually. The readiness check at idea exit catches this before refine
sees it.
