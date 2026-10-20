# Polish — advance

Until the through-stage: run the next stage's cases on the committed head,
then transition one declared edge.

```text
yoke qa plan run --item PREFIX-N --transition <next-stage>
yoke lifecycle transition PREFIX-N --from <live-stage> --to <next-stage> --reason "Polish verified"
yoke claims work release --item PREFIX-N --reason completed
```

Report lanes, verdicts, full commit hash and the next skill. Merge and deploy
are not polish.
