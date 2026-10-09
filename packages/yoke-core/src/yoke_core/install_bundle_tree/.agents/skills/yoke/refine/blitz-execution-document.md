# Refine — Blitz Execution Document

Only when ITEM_NEXT_SKILL=blitz, after verified artifact writes and before
the active-to-target transition. Registered strategy.doc.list/get and
strategy.execution.get/link are authority; metadata linking never acquires
the document claim. Blitz activation's doc_claim_activation gate owns it.

## 1. Read the existing execution link

```bash
yoke strategy execution get "$ITEM_REF" --project "$ITEM_PROJECT" --json
```

Existing intended slug: keep it and verify, no no-op link.
Different slug: block at the active stage and surface conflict.
Null execution document: select below.

## 2. Select exactly one document

```bash
yoke strategy doc list --project "$ITEM_PROJECT" --json
yoke strategy doc get <slug> --project "$ITEM_PROJECT" --json
```

Inspect plausible candidates. Precedence: explicit exact artifact slug,
otherwise one unique same-project document matching title/outcome/parent
relationship. Exactly one **unarchived** match is required; one unrelated
document is not a match. Zero/multiple matches: stop, release item claim
through registered authority and ask for slug. Do not guess, create children,
copy the plan to body, or create a strategy document without direction.

Cold-start content must state outcomes and slice boundaries, affected areas,
coordination dependencies, verification/delivery actions, unresolved decisions
and parent relationship (explicit no-parent when applicable). Incomplete
content requires plan repair before link or advance.

## 3. Link and verify

```bash
yoke strategy execution link "$ITEM_REF" --slug "$EXECUTION_SLUG" --project "$ITEM_PROJECT" --json
yoke strategy execution get "$ITEM_REF" --project "$ITEM_PROJECT" --json
```

Only strategy.execution.link writes this metadata; no SQL reconstruction.
Require execution.execution_document.slug equals EXECUTION_SLUG, linked_at
nonempty, one actual document object instead of a copied body/child plan,
the correct item/project and execution.item_claim matching this claim.

Retain slug for report. After lifecycle success resolve fresh next_skill_id,
release item claim and render:
```text
Next step: /yoke {NEXT_SKILL_ID} {ITEM_REF}
Execution document: $EXECUTION_SLUG
```
Follow [shared handoff](../shared/stage-handoff.md).
