# Documentation

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > Documentation
<!-- /yoke:breadcrumbs -->

Teach the next supported action with its prerequisites, a complete example and
an exact pointer to deeper detail. These nine clauses apply to human and agent
teaching in rules, hooks, packets, skills, docs, help, command replies,
installers and dashboard guidance.

## Shared teaching standard

1. **Teaching forms a tree.** Broad nodes cover every immediate child concisely;
   deeper nodes narrow scope and add detail. Every topic has a home, a
   discoverable path from the root and parent/child navigation. A surface can
   carry different depths.
2. **Teach everything needed now, extremely concisely.** Minimum needed now,
   exact pointer to more. Pointers supplement necessary instruction; remove
   repetition, filler and obvious handholding.
3. **Showing beats explanation.** Lead action teaching with the shortest complete
   examples of the right actions, including necessary prerequisites and expected
   results. Teach the supported action directly; reserve prohibitions for
   necessary boundaries.
4. **Teach before it matters.** Match audience, situation, permissions and
   global/project context. Required knowledge arrives before its action or
   decision; optional suggestions appear when useful.
5. **One authority, many appearances.** Maintain each rule, recipe and definition
   once; reuse concise versions wherever needed. Live facts and project policies
   retain their own authorities; public guidance never inherits private
   installation choices.
6. **Teaching must work.** Verify examples, reachable destinations and release
   compatibility in the receiving context. Refusals preserve their actual cause,
   necessary facts and supported recovery.
7. **350 lines is the hard maximum for every teaching file and displayed
   response.** The smaller targets below are advisory, not gates. Count displayed
   lines after wrapping at 80 columns; character counts include spaces and code.
8. **Preserve complete, coherent teaching.** Either advisory target prompts
   readability review, not arbitrary compression or splitting. Exceed a target
   when useful; subdivide at meaningful boundaries. Large results use narrower
   reads, pagination or saved evidence; never silently truncate essentials or
   corrupt structured contracts.
9. **Budget complete deliveries.** Existing stricter harness byte limits still
   apply to the combined payload, including messages and required recovery.
   Reuse the composer; optional material gives way first. Check actual delivery,
   not only installed files.

| Surface | Suggested lines | Suggested characters |
|---|---:|---:|
| Teaching file | No separate target; 350 hard maximum | 20,000 |
| Root help | 40 | 2,400 |
| Category help | 80 | 4,800 |
| Command help | 120 | 7,200 |
| Routine command reply | 40 | 2,400 |

## Author and check a branch

From a claimed source lane, add the page under `docs/public`, git-add it, and
give it one parent in `nav.yaml`. Then derive and check its navigation:

```text
python3 -m yoke_core.domain.documentation_render write --root docs/public
python3 -m yoke_core.domain.documentation_navigation check --root docs/public
python3 -m yoke_core.domain.documentation_links check --root docs/public
python3 -m yoke_core.domain.documentation_render check --root docs/public
python3 -m yoke_core.domain.documentation_render measure --root docs/public
```

In Yoke source development, run these through `yoke dev run --lane <lane> --`.
Navigation checks enforce schema, ownership, routes and listed pages; link
checks enforce targets and heading fragments; render checks enforce derived
blocks. Measurement enforces the 350 wrapped-line limit and reports advisory
readability notes. Scenario evidence must also prove discovery, usable recipes
and delivered context; passing structural checks alone cannot prove teaching.

<!-- yoke:contents -->
- [Navigation contract](navigation.md) — Share page routes, heading fragments and exact corpus identity.
<!-- /yoke:contents -->
