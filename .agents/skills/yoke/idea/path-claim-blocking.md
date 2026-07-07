# Idea — path-claim conflict resolution protocol

When `path-claims register` exits non-zero with an overlap or coverage
error, the new draft item cannot leave `idea` until the conflict is
represented in a sanctioned shape. This file is the canonical protocol
for that resolution; `body-and-sync.md` step 9b dispatches here.

**Cross-reference anchor.** Your `main_agent` packet's `claims` stanza
(`path_claims`, `path_claim_targets`, `path_targets`,
`path_claim_amendments`, `harness_sessions`, `work_claims`, `actors`)
plus the path-claim CLI cheat-sheet entries are the schema-side surface
the agent reads at session start; this file is the workflow-side
surface they point at when overlap registration denies. The Claude
session-rules cross-reference in `runtime/harness/claude/rules/session.md`
also routes mid-flow overlap denials here. The two surfaces are
deliberately layered — the packet teaches the shape, this file teaches
the resolution order.

**Coordination-edge authoring is owned by `/yoke idea` (this file) and
`/yoke refine` ([readiness-repair.md](../refine/readiness-repair.md)).**
The Engineer, Tester, Boss, Conduct, Polish, Advance, and Usher skills do
NOT author coordination edges — when a runtime path-claim collision
surfaces in those phases, route the operator back to `/yoke refine`
rather than authoring the edge inline.

## 0. Auto-classification: rendered-output overlap is a no-op

Before reaching this protocol, the classifier checks one structural
shortcut: when the overlap between the candidate and the existing
claim is **entirely on `FAMILY_RENDER_TARGET` paths** AND the two
claims' coverage is **disjoint at the seed-source layer**, the
classifier auto-returns `OverlapClassification.NONE` and the candidate
registers cleanly — no operator-authored `coordination_only` edge,
no escalation. This catches the case where two tickets each touch a
disjoint stanza of `runtime/api/domain/schema_api_context_*.py` and
the renderer deterministically regenerates the same agent packets. The
seed sources are disjoint, so the rendered overlap is not real
coordination.

Operator-visible signal: no `path-claim-register` error fires, and no
`item_dependencies` row is written. If you expected an overlap denial
on rendered packet files and got a clean register, this is why.

The renderer-to-context bridge that registers these relationships is
`runtime/api/domain/agents_render_path_context.py`; the
`HC-path-integrity` doctor surface (via the
`path_integrity_invariants_render_relationship` invariant) flags stale
registrations when a rendered target or its seed sources drift out of
the registry. Out of scope for this auto-classification: overlap that
mixes rendered targets with hand-authored paths (falls through to the
normal classifier), overlap on rendered targets whose seed sources
also overlap (still `INCOMPATIBLE` / `SERIAL_VIA_DEPENDENCY` per the
existing semantics), and non-packet rendered surfaces (BOARD,
event-catalog, function inventory, designs — not yet in scope).

## 1. Classify the overlap (mandatory first step)

Path-claim overlaps fall into three buckets, and you cannot pick the
shape that resolves the conflict until you know which bucket the overlap
is in. Default to the narrowest edge that fits — `coordination_only`
attests the overlap is compatible without gating lifecycle or
path-claim activation, so most independent overlaps belong there.
`activation` is a heavier hammer and must be backed by explicit
directional evidence. Always classify before authoring any dependency
row.

Run these inputs in order:

1. **Read both items' specs.** The candidate item's spec is open; read
   the conflicting item's spec via
   `yoke items get YOK-{conflicting-id} body`.
2. **Read the relevant sections of the shared paths.** Identify which
   blocks, functions, or subsections each ticket actually edits.
3. **Run the decision helper to gather evidence:**

   ```bash
   yoke claims path coordination-decision-build \
       --item YOK-{id-number} \
       --conflicting-claim {existing_claim_id} \
       --paths {shared-paths-comma-separated}
   ```

   The helper returns a context packet: both specs, the conflicting
   claim's state, path metadata, and three ready-to-paste commands —
   one per decision option (`coordination_only`, directional
   `activation`, operator `escalate`). The packet does NOT decide for
   you; you classify and pick the matching command.

   Do not hand-author overlap SQL before this helper runs. If you need
   to inspect claim coverage after the helper, ground the shape in your
   claims packet: `path_claim_targets.claim_id -> path_claim_targets.target_id
   -> path_targets.id`, with paths on `path_targets.path_string`.

Decision rules:

- **Independent edits** (different sections, different functions, no
  logical coupling) → section 2 (`coordination_only`). This is the
  expected path for most file-level overlaps in this codebase.
- **Order-dependent edits** (candidate work assumes upstream lands
  first, or upstream renames/restructures the surface the candidate
  edits) → section 3 (directional `activation`). Author only with
  explicit `decision=directional` rationale that names why order
  matters.
- **Genuinely ambiguous** (cannot tell whether the edits collide
  semantically) → escalate to the operator; do NOT author silently.

The classification is your decision and it is recorded in the `rationale`
field of whichever row you author. The doctor invariant
`path-claim-coordination-rationale` flags missing or stale attestations,
and the read-only review at `yoke_core.domain.path_claim_hard_block_review`
flags `activation` rows that look like path-claim-only hard blocks and
lack directional evidence.

## 2. Coordination-only edge (independent same-file edits)

When the path-claim overlap reflects two items editing the same file in
**semantically independent** ways (different sections, no logical
coupling), author a `coordination_only` edge. The edge is the agent's
explicit assertion that two items touch overlapping files but no
lifecycle ordering or path-claim mutex is required. Both items register
as `state='planned'` and activate independently; any same-hunk conflict
surfaces at PR-merge time as a normal git merge conflict and is resolved
by `yoke_core.engines.merge_worktree`.

```bash
yoke shepherd dependency-add \
    YOK-{id-number} YOK-{conflicting-item-id} idea \
    --gate-point coordination_only \
    --rationale "<non-empty: name shared paths, the disjoint sections each ticket edits, why the edits are independent>"
```

The `satisfaction` defaults to `fact:merged`. The rationale text is the
audit record — be specific enough that a reader (human or doctor HC) can
verify the independence claim from the rationale alone. Generic phrases
like "different concerns" or "no ordering required" are not enough.

Then re-run `register`; the resolver classifies the overlap as
`OverlapClassification.NONE` (no path-claim mutex) via the new edge and
the candidate registers as `state='planned'`.

## 3. Directional activation (order-dependent overlap)

When the path-claim overlap reflects a real serial ordering — the
candidate item assumes work that should run **after** the upstream
completes, or upstream restructures the surface in a way the candidate
inherits — author an `activation` edge. The activation gate point gates
lifecycle and keeps the candidate claim blocked until the upstream
coordination condition is satisfied.

`shepherd dependency-add` defaults to `--gate-point activation` when no
flag is passed, but the path-claim conflict-resolution protocol requires
the explicit flag plus a directional rationale so the row is
distinguishable from over-hard mistakes.

```bash
yoke shepherd dependency-add \
    YOK-{id-number} YOK-{upstream-id} idea \
    --gate-point activation \
    --satisfaction fact:merged \
    --rationale "decision=directional. <why order matters: name what upstream lands that this candidate inherits or depends on>"
```

Then re-run `register` without `--upstream-claim-id`; the resolver walks
`item_dependencies` and lands the candidate in `state='blocked'` with
`blocked_reason="serial-via-dependency on path_claims.id=N"`.

The same flow handles the multi-upstream case: every dependency edge
the candidate carries is read, and the resulting `path_claims` row's
`blocked_reason` updates as upstream releases land. A downstream claim
with multiple overlapping upstream blockers stays blocked until **every**
overlapping blocker has released, not just the one named in the current
`blocked_reason` snapshot.

## 4. Explicit upstream-claim pin (secondary)

When no dependency edge fits (e.g. you are coordinating with a single
upstream claim that does not represent a true ordering relationship and
the operator wants to make the pin explicit), `register` accepts an
explicit pin:

```bash
yoke claims path register \
    --item YOK-{id-number} \
    --paths file1.py --upstream-claim-id {claim_id}
```

When `--integration-target` is omitted, the register handler defaults
to the project trunk resolved from `projects.default_branch` (with a
fallback to `main`). Pass `--integration-target <branch>` explicitly
only when you intentionally want to gate the claim against a feature
branch rather than the trunk.

This produces a `state='blocked'` row but skips the dep-graph walk.
Prefer section 2 or 3 over this when an ordering or coordination
relationship is real, since the dep-graph is authoritative for
cross-ticket sequencing.

## 5. Mode='exception' for no-claim items (terminal alternative)

Some tickets legitimately touch no repo surface — validation-only,
evidence-only, meta. They should never block on path-claim overlap;
they declare an exception:

```bash
yoke claims path register \
    --item YOK-{id-number} \
    --mode exception \
    --reason "validation-only ticket: verifies YOK-{other-id} end-to-end"
```

## 6. Item-level block (LAST RESORT)

Use **only** when none of (2)–(5) can represent the conflict. The
flag-driven model gives the operator a sanctioned shape:

```bash
yoke items scalar update YOK-{id-number} --field blocked --value true
yoke items scalar update YOK-{id-number} --field blocked_reason \
    --value "<copy the path-claims register CLI error verbatim, plus the upstream coordination required to unblock>"
```

This preserves the lifecycle status (the item stays at `idea`/`refined-idea`)
and routes the row into the BOARD's Blocked section instead of leaving
it hidden in Active. Once the upstream coordination is resolved, the
operator runs `/yoke unblock YOK-{id-number}` to clear the flag and
re-run path-claim registration.

The forbidden state is "normal synced issue at `status='idea'` /
`status='refined-idea'` with zero claim, no exception, and `blocked=0`"
— the catch-up audit (`yoke_core.domain.path_integrity_invariants_claim_coverage`)
will surface it on the next pass and `/yoke refine` will refuse to
advance it past `refining-idea`.

Item-level `blocked` is the **only** fallback for cases where the
upstream conflict cannot be represented as a path-claim row. The
default is to use sections 2–5; reach for (6) when those genuinely do
not apply.

## Symlink-aware authoring advisory

When a declared File Budget path is an in-repo symlink (for example,
`CLAUDE.md` points at `AGENTS.md`), Yoke's registration chain
auto-pairs the symlink-name with its canonical target — the claim
covers both target_ids so a concurrent claim on either name is detected
as overlapping. The phase 3 path-closure validator surfaces a one-line
advisory in that case:

> `<symlink>` is a symlink to `<canonical>`; Yoke will claim both — list
> `<canonical>` in the File Budget so the human-readable surface matches.

The hint is advisory; creation proceeds either way. It nudges the
operator toward listing the canonical name on the next refinement so
the File Budget converges on the durable surface rather than carrying
both names defensively.

## Widening an existing claim — `yoke claims path widen`

When refine discovers additional paths the existing claim should cover
(File Budget grew, sibling-module split landed, runtime collision routed
back from a later phase), widen the claim through the canonical wrapped
agent CLI:

```bash
yoke claims path widen \
    --claim-id {claim_id} \
    --add-paths file1.py,file2.py \
    --reason "<authored rationale>" \
    --item YOK-N
```

The function id is `claims.path.widen`. The legacy service-client
`path-claim-widen` form is operator/debug fallback only — still valid,
just not the agent-facing teaching shape. Both surfaces dispatch through
the same handler.

## Verifying the resolution

After registering (or after setting the flag in case (6)), confirm
coverage by running the gate:

```bash
yoke claims path required-gate YOK-{id-number}
```

`verdict=pass` means the candidate is gate-clean and the item can leave
`idea`. `verdict=block` surfaces a remediation `reason` — read it,
amend the claim or the dep-graph, and retry.
