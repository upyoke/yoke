# Idea — Finished-Spec DB Classification

After full spec write/readback, classify its actual deliverables.
**Why bucket discipline matters:** state:none with reviewed_negative evidence
clears prose mismatch regardless of reason. It must never hide real mutation
behind a false reviewed-none or silently deferred declaration.

## 1. Detect against checked content

Portable local product adapter works without ambient runtime imports/local DB:
```bash
_spec_json=$(yoke items get "$ITEM_REF" spec --json) || exit 1
_spec=$(printf '%s' "$_spec_json" | python3 -c 'import json,sys; d=json.load(sys.stdin)["result"]["fields"]["spec"]; print(d) if isinstance(d,str) and d.strip() else sys.exit("Unread or empty spec")') || exit 1
if [ -z "$_spec" ]; then
  echo "Unread or empty spec: refusing DB-claim default" >&2
  exit 1
fi
printf '%s' "$_spec" | yoke db-claim prose-check --stdin --public-ref "$ITEM_REF" --json
```

A failed/empty read must not reach a detector whose empty input reports no
triggers. Inspect result.blocks and matched triggers; failed/malformed detector
response is not zero. Item-targeted prose-check may be used only after its
serving capability is verified; do not infer a server function from local help.

## 2. No triggers

Amend state:none through db_claim.amend with exact reason:
`idea: spec/body declares no governed DB mutation`.
This stamps deliberate negative evidence instead of creation's implicit default.

## 3. Triggers: one ternary decision

Present matched triggers and these mutually exclusive choices:
1. **Real governed mutation, declare now**: gather authoritative model,
   apply/retire intent, module slugs, compatibility class and four authored
   attestation fields for pre_merge_safe; amend full unified declared claim.
2. **Real governed mutation, blocker for refine**: add the field-targeted
   **DB Claim Blocker (idea-time)** section with known/missing facts.
   Do NOT call `db-claim-amend` or db_claim.amend. Implicit state:none plus
   missing amendment evidence intentionally blocks GATE_DB_CLAIM_PROSE_MISMATCH
   until Refine declares the real mutation.
3. **Meta work item about DB governance**: actual deliverables mutate no
   governed authoritative DB. Amend state:none with exact reason
   `idea: work item discusses DB governance vocabulary but performs no governed DB mutation; reviewed-none`.
   Preserve literal `; reviewed-none`; real mutation cannot use this bucket.

Blocker template:
```text
## DB Claim Blocker (idea-time)
Real governed mutation: Refine must declare the unified claim before handoff.
Known facts:
- Authoritative DB/model: <known-or-unknown>
- Mutation intent: <apply-or-retire-or-unknown>
- Planned module slugs: <known-or-unknown>
- Compatibility: <pre_merge_safe-or-pre_merge_breaking-or-unknown>
- Affected surfaces: <actual-touch-set>
Missing facts that block declared payload:
- <missing-required-fact>
```

## 4. Persist and verify

```bash
yoke db-claim amend "$ITEM_REF" --reason "<exact-applicable-reason>" --stdin
yoke items get "$ITEM_REF" db_mutation_profile
```

Only buckets1/3 execute amendment/readback; bucket2 intentionally leaves
unstamped default. The upsert-safe unified workflow owns profile+attestation;
never edit raw JSON. This classification is mandatory.

## 5. Apply modules: permanent history AC

For bucket1 apply intent with modules, add the concrete module-naming permanent
history AC from [body-and-sync-functions.md](body-and-sync-functions.md).
Safe reruns, boot convergence and never deleting ordered modules are required
for every installation. Use the actual field-targeted/additive adapter; no
invented field flag on section-append or topology-specific retirement.
