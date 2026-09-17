---
name: strategize
description: "Direct-mode entrypoint — guided SML review across the MISSION, LANDSCAPE, VISION, MASTER-PLAN, and CURRENT-PLAN strategy docs."
argument-hint: "[--lane LANE] [--model MODEL]"
---

# /yoke strategize

Guided interactive loop for Strategic Markdown Layer (SML) coherence. Refreshes the SML docs against recent reality, performs source-backed research, proposes changes, obtains operator approval, and records audit trail.

The strategy authority is the Yoke DB `strategy_docs` table, scoped per project; the checkout's `.yoke/strategy/*.md` files are gitignored local rendered caches (the seeded `.yoke/.gitignore` `strategy/` rule keeps them out of git, so they are not tracked or committed). Reads go through `yoke strategy doc get <SLUG>`, writes through `yoke strategy doc replace <SLUG> --base-updated-at <TS>` (compare-and-swap; auto-renders the latest full strategy corpus into the checkout). The durable record of an approved change is the DB write plus the `SMLChangeApproved` event.

Strategize is the "compass" mode -- it ensures Yoke always has a clear, current strategy to charge against. It shapes strategy and frontier coherence, but does not own per-item dependency ordering or session assignment logic (those belong to `feed` and the scheduler).

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `--lane LANE` -- Execution lane identity (default: `DARIUS`).
- `--model MODEL` -- Model identifier override.

## Constants

```
REPO_ROOT=$(git rev-parse --show-toplevel)
SML_SLUGS="MISSION LANDSCAPE VISION MASTER-PLAN CURRENT-PLAN"
_project=$(yoke projects checkout-context --field slug)
_project_id=$(yoke projects checkout-context --field id)
```

`_project` is the slug of the checkout's mapped project (the machine-config checkout→project map; abort with the printed teaching if it fails) — strategize operates on THAT project's strategy corpus, claim group, and frontier. The `yoke strategy ...` commands default to the same checkout mapping, so bare invocations stay correct; every raw SQL line below scopes by `$_project_id` explicitly.

`SML_SLUGS` names the strategy-doc slugs this loop reviews (`yoke strategy doc get <SLUG>` reads each; `yoke strategy doc list` shows the project's full corpus with each row's `updated_at`).

## Philosophy

**Be the giant.** We stand on inherited shoulders; leave a leg up for the next agent. Strategize should leave standing decisions, holds, and rationale in the documents themselves. Later sessions inherit current strategy, not a pile of unexplained edits or historical snapshots.

**Think across generations.** Strategy work is where the metaphor matters most: inherit context from prior cycles, improve it, and hand back a clearer frontier than the one you received.

## Phase map — read one file, at the phase it governs

| Phase | You are here when | Read before acting |
|---|---|---|
| 1–3. Parse, claim, dispatch | `/yoke strategize` was just invoked | [`entry.md`](entry.md) |
| — Look up a strategy surface | You need a strategy operation's exact envelope | [`surfaces.md`](surfaces.md) |

The phase dispatch in `entry.md` names the one phase file each stage needs —
[`refresh.md`](refresh.md), [`research.md`](research.md),
[`propose.md`](propose.md), [`approve.md`](approve.md),
[`finalize.md`](finalize.md). Read the one the dispatch selects.

## Start

Read [`entry.md`](entry.md) and follow it.
