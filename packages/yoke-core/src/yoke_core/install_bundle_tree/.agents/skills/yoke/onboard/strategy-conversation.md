# Onboard Step 1: Strategy Conversation

Rows: `repo-survey`, `strategy-setup`.

1. Name the scan: open issues/PRs and checkout transcripts per harness
   manifest. Ask what else belongs.
2. Seed, then read MISSION, VISION, MASTER-PLAN, LANDSCAPE, CURRENT-PLAN.
3. Offer to move work-specific `AGENTS.md` rules into execution instructions.
   Per approved rule: create, `set-scope` (unscoped reaches no work), resolve,
   then delete the moved text from its source.
4. Have the operator write goals and a high-level plan in CURRENT-PLAN,
   defined enough for parallel dashes; preserve open work. Ask one decision
   at a time.
5. Write under the STRATEGIZE claim; release it on every exit, then render.

```text
yoke github open-work list --project {project} --json
yoke strategy seed-defaults --project {project} --json
yoke claims work acquire --process STRATEGIZE --project {project}
yoke strategy doc replace {SLUG} --project {project} --base-updated-at {updated_at} --content-file {draft_path}
yoke strategy render --project {project} --target-root {checkout}
```
