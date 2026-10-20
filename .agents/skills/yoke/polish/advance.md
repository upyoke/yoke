# Polish — advance

Until the through-stage: run the next stage's cases on the committed head,
then transition one declared edge.

```text
yoke qa plan materialize --item PREFIX-N --transition <next-stage>
yoke qa plan run --item PREFIX-N --transition <next-stage>
yoke lifecycle transition PREFIX-N --from <live-stage> --to <next-stage> --reason "Polish verified"
yoke claims work release --item PREFIX-N --reason completed
```

Exit 12: dispatch the returned review bundle and submit its verdicts;
pending review is not a pass. Report lanes, verdicts, full commit hash
and the next skill. Merge and deploy are not polish.
