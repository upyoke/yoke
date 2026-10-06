## 8b. Late DB-Claim Classification

After the body has been written and verified (step 8 complete), classify and persist the DB claim against the **finished spec**, not against the title-only draft. This is the same amendment workflow `refine`, `implement`, and `polish` use later — there is no separate "first classification" path.

**Why bucket discipline matters:** The prose-vs-claim gate honors any stored `state="none"` profile carrying the workflow-stamped `reviewed_negative` attestation as cleared evidence, regardless of the reason text. The three-bucket discipline below is therefore the only signal that distinguishes reviewed-none meta work items from silent deferral bypasses; getting the bucket right at idea time is load-bearing.

1. Run the prose-vs-claim detector against the freshly written spec.
   Prefer the stdin mode — it runs locally through the installed ``yoke``
   CLI (no ambient ``yoke_core`` import, no local DB) and works on https
   control planes. Check the spec-read exit and content **before** piping
   into the detector; a failed read must not reach it (empty stdin reports
   "no triggers" and would stamp ``state="none"`` on unread content). Do
   **not** call
   ``python3 -m yoke_core.domain.db_claim_prose_check check-item``:

   ```bash
   _spec=$(yoke items get "PREFIX-{N}" spec)
   if [ $? -ne 0 ] || [ -z "$_spec" ]; then
     echo "Error: failed to read spec for PREFIX-{N}; refusing DB-claim default" >&2
     exit 1
   fi
   _prose_check=$(printf '%s' "$_spec" | yoke db-claim prose-check --stdin --public-ref "PREFIX-{N}" --json)
   _prose_blocks=$(printf '%s' "$_prose_check" | python3 -c "import json,sys; r=json.load(sys.stdin); print('1' if (r.get('result') or {}).get('blocks') else '0')")
   ```

   After the control plane serves ``db_claim.prose_check``, the item-targeted
   form ``yoke db-claim prose-check PREFIX-{N} --json`` also works and
   composes against the stored claim profile.

2. **No triggers detected (`_prose_blocks=0`):** explicitly stamp the
   negative-default claim through the canonical workflow so the item
   carries an event-attested `state="none"` rather than the implicit
   creation default. Dispatch the `db_claim.amend` function call
   (envelope in
   [`body-and-sync-functions.md`](body-and-sync-functions.md)) with
   `target = {kind: "item", public_ref: "PREFIX-N"}` and
   `payload = {reason: "idea: spec/body declares no governed DB mutation", claim: {state: "none"}}`.

   The reason text is canonical — do not paraphrase. It is the only
   `state="none"` reason emitted on the no-DB-work path.

3. **Triggers detected (`_prose_blocks=1`):** the agent presents the
   matched triggers, then asks one ternary question. The buckets are
   mutually exclusive, and `state="none"` is **not** a valid deferral
   path for real governed mutation — pick the bucket that actually
   describes this work item's deliverables. Canonical prompt:

   > Spec declares governed DB vocabulary (`{triggers}`). Pick one:
   >
   > 1. **Real governed mutation, declare now** (Bucket 1) — gather model, mutation intent, migration module slug, compatibility class, and (for `pre_merge_safe`) the four authored attestation fields. Dispatch `db_claim.amend` with the unified declared `claim` payload (see [.yoke/docs/reference/db-reference.md](../../../../.yoke/docs/reference/db-reference.md)).
   > 2. **Real governed mutation, blocker for refine** (Bucket 2) — append a `DB Claim Blocker (idea-time)` section via `items.structured_field.section_upsert` listing known + missing facts. Do NOT call `db-claim-amend`; do NOT dispatch `db_claim.amend` — the implicit `{"state":"none"}` default plus the missing event signals `/yoke refine` to block at `GATE_DB_CLAIM_PROSE_MISMATCH` until a declared payload lands.
   > 3. **Meta work item about DB governance** (Bucket 3) — the work item cites DB vocabulary but its own deliverables do not mutate any governed authoritative DB (skill prose, gate composition, prose-classifier patterns, audit-trail vocabulary). Dispatch `db_claim.amend` with `payload.claim = {state: "none"}` and `payload.reason = "idea: work item discusses DB governance vocabulary but performs no governed DB mutation; reviewed-none"`. The literal `; reviewed-none` suffix is the canonical signal — do not paraphrase.

   Bucket 2 blocker section template:

   ```
   ## DB Claim Blocker (idea-time)

   This work item performs governed DB mutation but the declared claim could not be authored at idea time. `/yoke refine` MUST dispatch `db_claim.amend` with a declared `claim` payload before this item can advance past `refining-idea`.

   Known facts:
   - Authoritative DB / model: {known-or-unknown}
   - Mutation intent (apply / retire): {known-or-unknown}
   - Migration module slug (planned): {known-or-unknown}
   - Compatibility class (pre_merge_safe / pre_merge_breaking): {known-or-unknown}
   - Affected surfaces: {free-form list}

   Missing facts that block declared payload:
   - {item}
   ```

4. Verify the claim landed (buckets 1 and 3 only — bucket 2 leaves the
   schema default in place by design) via the `items.get.run` function
   call with `fields: ["db_mutation_profile"]`.

This step is mandatory. The amendment workflow is upsert-safe (idempotent
against missing prior state) and stamps the reviewed-negative attestation
onto the stored profile, so the item itself shows the claim was
deliberately set at idea-creation time rather than left as the schema
default. Bucket 2 is the only path that intentionally leaves the schema
default — an unstamped profile on the blocker path is desired.

5. **Bucket 1, `mutation_intent="apply"` — emit the permanent-history AC.**
   When the payload names migration modules, the spec must require each entry
   to remain in ordered history and be safe to re-run. There is no
   topology-specific deletion path. See `body-and-sync-functions.md` under
   "Permanent-history AC clause"; write the addendum through
   `items.structured_field.section_append` so the rest of the spec is
   preserved.
