# Onboard Step 1: Strategy Conversation

Rows: `repo-survey`, `strategy-setup`.

1. In one message, name what you will scan (open issues/PRs, this checkout's
   transcripts per harness manifest) and ask what else belongs.
2. Seed, then read MISSION, VISION, MASTER-PLAN, LANDSCAPE, CURRENT-PLAN.
3. Offer to move work-specific `AGENTS.md` rules into execution instructions.
   Per approved rule: create, `set-scope` (unscoped reaches no work), resolve,
   then delete the moved text from its source.
4. Draft; carry open work forward. Ask decisions one at a time, the first work last.
5. Write under the STRATEGIZE claim; release it on every exit, then render.

```text
yoke github open-work list --project {project} --json
yoke strategy seed-defaults --project {project} --json
yoke claims work acquire --process STRATEGIZE --project {project}
yoke strategy doc replace {SLUG} --project {project} --base-updated-at {updated_at} --content-file {draft_path}
yoke strategy render --project {project} --target-root {checkout}
```
