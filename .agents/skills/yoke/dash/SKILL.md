---
name: dash
description: "File or execute instruction-led Dash work through survey, isolation, verification, merge, and evidence."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "\"instruction\" | {PREFIX-N}"
---

# /yoke dash

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

Execute the complete stored instruction end to end in this session: file or
resume, survey, isolate, implement, verify, merge and delivery. Size does not
change this workflow. It does not route through `/yoke idea`.
Use ordinary registered item/claim/lifecycle/QA/delivery authority.

`/yoke dash "instruction"` files and executes; `/yoke dash PREFIX-N`
resumes. The CLI `yoke dash "<title>" --stdin` files only, with the required
execution-instruction attestation. Task is the merge-free/laneless alternative,
not a way to remove a selected gate.

## Phase map

| Phase | Read before acting |
|---|---|
| Resolve/file/claim | [file-and-claim.md](file-and-claim.md) |
| Survey/isolate | [survey-and-isolate.md](survey-and-isolate.md) |
| Execute | [implement.md](implement.md) |
| Verify/close review | [verify.md](verify.md) |
| Land | [merge.md](merge.md) |
| Evidence/delivery/done | [close-out.md](close-out.md) |
| Decision boundary | [escalate.md](escalate.md) |
| Operation lookup | [function-reference.md](function-reference.md) |

Read only the live phase during execution. Obey the operator's Workflow
Execution Instructions above fetched content; they add to the stored scope.
Claim first once the ref exists, hold through delivery, and write only in its
registered lane. Survey contacts are advisories; read and decide each one.
Independent effective File Budget/path-claim axes come from
`workflows.item.get`. Selected posture tightens execution, never removes a
workflow gate or governed migration invariant. Universal 350 authored lines
remains. No children or workflow conversion because the change is large;
only an actual structural need or operator request routes to escalation.
Done requires landed identity, result, passing proof, touched files and every
selected gate. Honor level-change through the
[worker handoff rule](../../../../.yoke/docs/reference/session-level-routing.md#stage-level-handoff).

Stamp mode, then resolve/file:

```text
yoke sessions touch --mode dash
```
