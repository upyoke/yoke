# Consumer proof

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Verification](index.md) > Consumer proof
<!-- /yoke:breadcrumbs -->

Declare a consumer's proof workflow once. Matching producer candidates then
run it automatically before merge, and the producer item's QA requirement
records the consumer commit, workflow inputs, run URL and verdict.

## Declare a consumed contract

Use `projects.capability_settings.merge` on the **consumer** project. The
`consumer-proof` capability maps producer project slugs to their consumed
repository paths and the workflow that proves compatibility:

```text
yoke projects capability-settings merge --project consumer \
  --cap-type consumer-proof \
  --set 'producers.producer={"contract_paths":["api/**"],"workflow":"consumer-build.yml","candidate_input":"product_ref"}'
```

Replace both project slugs, the producer-relative globs and workflow filename
with registered project facts. The consumer must have a GitHub repository
binding, a default branch and a workflow that accepts the candidate input and
the reserved `yoke_dispatch_id` correlation input. The caller needs access to
the consumer project's repository operations. `inputs` optionally supplies
additional nonempty string workflow inputs; it cannot replace either reserved
input. `candidate_input` defaults to `product_ref`.

The capability contains no credentials. An invalid declaration refuses before
it is saved; correct the named field and retry the settings write. A consumer
with no declaration contributes no merge check. A declared producer whose
changed paths match none of the contract globs dispatches no consumer run.

## Merge and evidence

Run the producer's ordinary verification and `yoke merge item PREFIX-N`.
Both queue and standalone merge routes run consumer proof after producer
verification and publication. The gate uses the integrated candidate's full
commit, never an earlier local head. It binds the consumer's default-branch
commit through an immutable dispatch tag, then dispatches its declared
workflow with that exact producer candidate as an input.

The existing correlated workflow dispatcher and CI waiter own dispatch and
waiting. Identical candidate/consumer/workflow/input pairs rejoin their
durable dispatch; a changed pair gets its own identity. The returned consumer
run must conclude successfully on the bound consumer commit. A success on a
different commit cannot satisfy the check.

The producer requirement has suite id `consumer-proof:<consumer slug>`.
Its QA run records both commits and the actual workflow result. A failed run
blocks merge and names the consumer run and failing job. Restore access for
`consumer_proof_unavailable`; fix the named build failure for
`consumer_proof_failed`, then retry the merge. A timeout keeps the candidate
unproven; retry joins the original run. No deployment run is created.

Verification alone needs no companion item or steering-arranged dispatch.
When the consumer itself needs code changes, create its linked companion and
verify that adaptation against the exact producer candidate. A producer's
passing tests alone cannot establish consumer compatibility.

## Related

- [Verification](index.md)
- [Project scoping](../agents/rules/lanes-and-claims.md#project-scoping)
