# Idea — Persist, Verify, Close

## 8. Full spec is mandatory

Anything beyond title is description. Preserve every user line, code block,
table, mockup, question and ASCII artifact **verbatim**; add structure/notes,
never summarize or paraphrase. Include Pack Reuse when inferred.

Every body has an advisory **Simplify Pre-Check**: reuse (what existing item,
feature, Pack/helper/skill/command was searched), quality (one outcome/non-goals),
efficiency (cheapest valuable path, no speculative temporary work), future-concept
(shared-state primitive or absorption), codebase-reader naming (current-purpose
surfaces without planning artifact). One-line no concerns is valid first intake.

Read result.effective_policies.file_budget and .path_claims once through workflows.item.get:
required item, required_per_task tasks, optional off; no raw-policy reconstruction.
Universal350 still applies. Follow [file-budget.md](file-budget.md) for the
sole complete budget structure and current counts/sibling rules. Pair axes only
when both enabled; claims alone derive full scope, budget alone has no claim,
neither creates neither. Required overlapping files never disappear.
When File Budget is off, omit that section.

Enabled implementation-bearing budget follows pre-check before ACs:
known exact file shape, UNRESOLVED unknown shape (Refine must resolve before
handoff), or N/A with honest no-code-growth reason. If code is discovered later,
add a real budget before coding. The design target is<=300, hard350.
ACs use canonical `- [ ] AC-N: ...`; normalize labels without losing content.

No supplied description: ask once whether to add one. If declined, still write
title plus all pre-check lenses and the appropriate enabled budget shape.
Do not leave a title-only row as successful intake.

Write authored complete spec through items.structured_field.replace, guards
enabled; additions use dedicated additive/section transforms:
```bash
yoke items structured-field replace "$ITEM_REF" --field spec --source idea --stdin < <authored-artifact-path>
```

No inline payload or direct rendered-body write. Read back spec, rather than
duplicate body+spec. Empty/title-only unexpected result retries once after
checking live state. Standalone normalize_ac_labels reads stdin/file only;
DB normalization belongs to the pinned planning procedure.

## 8b. Finished-spec DB claim

Follow [db-claim-classification.md](db-claim-classification.md) after readback.

## 9. Complete enabled claims

Exclusive existing paths, allow_planned new paths, or justified exception;
session is provenance, owner_kind=item. Required_per_task before persisted task
files deliberately defers registration; never substitute an unbound parent.
After tasks exist repair each task scope. Registered adapters:
```bash
yoke claims path register --item "$ITEM_REF" --paths <complete-paths>
yoke claims path register --item "$ITEM_REF" --paths <complete-paths> --allow-planned
yoke claims path register --item "$ITEM_REF" --mode exception --exception-reason "<verified-no-repo-surface>"
yoke claims path required-gate "$ITEM_REF"
```

Pass/deferred pre-task pass continues; block reads the reason and repairs.
Overlap first follows [path-claim-blocking.md](path-claim-blocking.md):
attested independent coordination_only versus directional activation;
secondary upstream pin, honest exception or item blocked flag only when warranted.
Never set status=blocked or drop required scope. A synced normal idea without
claim/exception/blocked flag is forbidden. Any rollback before GitHub sync still
uses sanctioned mutation authority; never delete history ad hoc.

## 10. Sync and readiness before release

Default/attached QA plans materialize at their transitions; no type/Browser
posture-derived requirements. Add qa.requirement.add only for authored coverage
outside plans. Explicit body sync:
```bash
yoke items github-sync "$ITEM_REF"
yoke readiness check "$ITEM_REF" --json
```

Skip GitHub body sync only for the expressly declined-description title-only
case allowed by the actual persisted result, not a lost body write.

The draft claim **stays held** until actual verdict=pass:
- pass, including documented UNRESOLVED deferral at idea/source entry:
  complete path closure, release then confirm.
- block: keep claim and actual idea stage; show remediation, not next-step refine.
- unavailable: unperformed checks neither prove nor disprove; show every
  unavailable_checks check/recovery. Keep claim; retryable:false means no
  same-host loop. Recover on a registered target-project checkout host.

Checks use the item's registered project tree: function refs, current budget
counts and sibling plan at>=330, conditional coverage parity. Missing host inputs
are unavailable, never guessed against another repo or called passed.

This is **repair-before-block**: advisory diagnostic scope, blocking release
order. Refine's mandatory classifier repairs recoverable budget/claim drift
through claims.path.widen and claims.path.amend, retaining the work claim.
Its registered removal adapter binds named removed paths and integration target.
An audited --skip-readiness-check may yield a passing override; it cannot bypass
release-after-pass ordering. Read actual verdict, never exit0 alone.

## 10c. Release and confirm

Only after pass and [path-closure.md](path-closure.md):
```bash
yoke claims work release --item "$ITEM_REF" --reason idea-complete
```

Use acquire's actual claim_id on typed dispatch. Idea-complete stores handed_off,
preserves release_reason_intent on WorkReleased, and emits IdeaClaimHeld with
duration/claim/draft-in-progress provenance. No error/dry-run release; name
release failure. Frontier guards incomplete bodies even after stale reclaim.
Then render infer-and-create's fresh confirmation/handoff.
