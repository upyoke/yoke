---
name: strategize
description: "Review and update the MISSION, LANDSCAPE, VISION, MASTER-PLAN and CURRENT-PLAN strategy docs."
argument-hint: "[--model MODEL]"
---

# /yoke strategize

Guided review and approved edits of the strategy docs.

Docs (MISSION, LANDSCAPE, VISION, MASTER-PLAN, CURRENT-PLAN) live in DB rows;
`.yoke/strategy/` is a gitignored render. Claim first; `claim_conflict`
stops. Any abort releases the claim:

```text
yoke claims work acquire --process STRATEGIZE --project <project>
yoke claims work release --process STRATEGIZE --project <project> --reason "strategize abort"
```

Phase map, in order: [refresh](refresh.md), [research](research.md),
[approve](approve.md), [finalize](finalize.md).
