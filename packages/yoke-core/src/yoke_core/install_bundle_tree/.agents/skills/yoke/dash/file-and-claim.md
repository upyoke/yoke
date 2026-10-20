# Dash — file and claim

Resolve the project; never assume this checkout. Obey its instructions, then file the spec unchanged (put requested delivery or approval posture on the same create):

```text
yoke workflow execution-instruction resolve --workflow dash --project PROJECT --full
yoke dash --title "<specific title>" --project PROJECT --spec-file /tmp/dash-spec.txt --execution-instructions-considered --json --entry-surface harness_skill
```

Claim before any survey or edit, and hold it through delivery:

```text
yoke claims work acquire --item ITEM --reason "Dash execution"
yoke items detail get ITEM --include '' --json
```

On resume read the Progress Log and the lane's `git status`; lane state wins. Before any stop short of done, checkpoint with `yoke items progress-log append ITEM --headline "<checkpoint>" --stdin`. Next: [survey-and-isolate](survey-and-isolate.md).
