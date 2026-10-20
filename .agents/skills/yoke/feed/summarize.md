# Feed — Summarize

```text
yoke events emit --name FeedCompleted --project <project> --kind lifecycle --type feed --source-type skill --severity STATUS --outcome completed
yoke claims work release --process FEED --project <project> --reason completed
```

Report exact refs: landings, item and edge changes, coherence, open
questions, and any `--no-new-items` suppression.
