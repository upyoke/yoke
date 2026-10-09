# Shepherd — parse, persist and disposition

## Five-layer parse (first successful extraction wins)

Initialize verdict source and DB row ID empty:
1. Strict case-sensitive line ^VERDICT:\s*(READY|NOT_READY|CAVEATS)\s*$.
2. Existing accidental self-persistence recovery: query exact public_ref/edge/
   worker with id > pre-dispatch maximum, newest one only. Accept READY/
   NOT_READY/CAVEATS with caveats; older attempts never qualify.
3. Case-insensitive verdict:/verdict is/recommend or recommending/issuing plus
   ready/not_ready/not ready/caveats; or standalone tokens in last 20 lines.
   Normalize; conflicting matches choose nearest output end.
4. One-shot lightweight Boss extraction, maxTurns=1, no tools/explanation:
   return exactly VERDICT: READY/NOT_READY/CAVEATS or INDETERMINATE.
   Parse strict layer-1 pattern; INDETERMINATE falls through.
5. NOT_READY safety default plus [UNPARSEABLE_BOSS_OUTPUT], preserve full
   reasoning, continue bounded retries.

```text
yoke db read "SELECT id,verdict,COALESCE(caveats,'') FROM shepherd_verdicts WHERE public_ref='ITEM' AND transition='EDGE' AND worker='WORKER' AND id > PRE_DISPATCH_MAX ORDER BY id DESC LIMIT 1"
```

Source markers are layer1_regex/layer2_db/layer3_fallback/layer4_extraction/
layer5_unparseable. Layers 3–4 prepend [FALLBACK_PARSED] and log extraction route;
they do **not** increment the two-genuine-unparseable model escalation count.

CAVEATS extraction: numbered list following verdict. Layer4 with no list may
ask once "Also extract the caveats list." Still absent: persist
[FALLBACK_PARSED] [Caveats not extractable -- review Boss output manually],
keep full Boss output/feedback; do not invent caveats.

Full Boss retry after layer5: authoritative scope-aware reads only
(spec/prd → spec, body if empty; plan → technical_plan/worktree_plan with
spec/design context/body if empty), no broad codebase exploration;
FIRST output line must be VERDICT. Include full prior reasoning.

## Persist exactly once

CAVEATS = numbered list; NOT_READY = full feedback; BLOCKED = blocking reason;
READY = empty caveats. Worker identifies artifact producer/review role.
Layer2 reuses its anchored fresh row ID, no duplicate insert. Otherwise
shepherd.verdict.run creates the row; request JSON on original write and keep
result.verdict_id:

```bash
yoke shepherd verdict --item ITEM --transition EDGE --worker WORKER --verdict VERDICT --caveats "{reason or numbered caveats}" --json
```

Verified ambient identity owns the write. Failure stops; no advancement.
Extract worker/Boss reflection entries (REFLECTION start/end, BEGIN/END ENTRY,
timestamp/agent/context/category/observation) through existing Ouroboros/hook
contract; persist each once, not duplicate an already-hook-recorded entry.
Telemetry success is never verdict authority.

## All caveats need a disposition before advance

- RESOLVED requires an artifact edit **just made**, naming exact field/section/
  change. "Already handles this" or "no changes needed" is ANALYZED.
- DEFERRED implementation concern persists in shepherd_caveats and, if it names
  a task number, that task body so the next worker sees it.
- ANALYZED persists caveat and defensible reasoning for human verification;
  it cannot vanish into verdict storage. Ambiguous operator decision stops
  with evidence/Progress Log and required guidance.

Persist every one, 1-based index and exact verdict row/attempt:

```bash
yoke shepherd caveat-disposition --item ITEM --transition EDGE --attempt {attempt} --caveat-num {caveat_num} --caveat-text "{caveat}" --disposition RESOLVED --resolution-details "{specific edit and persisted destination}" --verdict-id {verdict_id}
```

Collect DEFERRED/ANALYZED as:
- **Caveat N:** text — *DISPOSITION:* details.
RESOLVED stays fixed in place. Print full triage including specific edits.

Write the collected nonempty transition subsection once with the producer's
field-targeted items.structured_field.section_upsert, heading level 3:
create if absent, append for new edge, replace only same edge on retry.
No read-transform shell surgery, no empty erasure, no other-field mutation:

```bash
yoke items structured-field section-upsert ITEM --field shepherd_caveats --heading-level 3 --section EDGE --content-file CAVEATS_FILE --source shepherd --json
```

Receipt must name the stored field/heading/section and verified write;
failure retains stage and named recovery. Body rerender is handler-owned.
