# Polish — advance

Until the through-stage: run the next stage's cases on the committed head,
then transition one declared edge.

```text
yoke qa plan materialize --item PREFIX-N --transition <next-stage>
yoke qa plan run --item PREFIX-N --transition <next-stage>
yoke lifecycle transition PREFIX-N --from <live-stage> --to <next-stage> --reason "Polish verified"
```

Exit 12: dispatch the returned review bundle and submit its verdicts;
pending review is not a pass. Report lanes, verdicts, full commit hash
and the next skill via [shared handoff](../shared/stage-handoff.md).

If your launch instruction is a single-item mandate for this item, keep the
claim and run `/yoke {next_skill_id} ITEM` now: read and follow the next
bound skill in this turn. Otherwise show the next-skill line and release
the claim. A transition's `level_change` handoff takes precedence: release,
launch the returned successor, and end; follow `.yoke/docs/agents/levels.md`.
