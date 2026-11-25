# Polish — advance

Until the through-stage: run the next stage's cases on the committed head,
then transition one declared edge.

```text
yoke qa plan materialize --item PREFIX-N --transition <next-stage>
yoke qa plan partitions --item PREFIX-N --transition <next-stage>
```

Run command-only and lane cases and launch free walk partitions using
`.yoke/docs/verification/walking.md#launch-a-walker`. When no partition is free, held or blocked,
run `yoke lifecycle transition PREFIX-N --from <live-stage> --to <next-stage>
--reason "Polish verified"`. Report lanes, verdicts, full commit hash
and the next skill via [shared handoff](../shared/stage-handoff.md).

If your launch instruction is a single-item mandate for this item, keep the
claim and run `/yoke {next_skill_id} ITEM` now: read and follow the next
bound skill in this turn. Otherwise show the next-skill line and release
the claim. A transition's `level_change` handoff takes precedence: release,
launch the returned successor, and end; follow `.yoke/docs/agents/levels.md`.
