# /yoke implement — review and handoff

1. Enter the review stage; keep the claim.
2. Review against the spec and every AC; fix, commit, rerun stale QA.
3. Transition one stage at a time to the through-stage:

```text
yoke qa gate-summary --item PREFIX-N --target <handoff-stage>
yoke lifecycle transition PREFIX-N --from <live-stage> --to <next-stage> --reason "Implementation review"
```

4. If a steering seat must act, `yoke say --steering` first. After a
   successful handoff, reread the item and follow [shared handoff](../shared/stage-handoff.md).

If your launch instruction is a single-item mandate for this item, keep the
claim and run `/yoke {next_skill_id} ITEM` now: read and follow the next
bound skill in this turn. Otherwise show the next-skill line and release
the claim. A transition's `level_change` handoff takes precedence: release,
launch the returned successor, and end; follow `.yoke/docs/agents/levels.md`.
