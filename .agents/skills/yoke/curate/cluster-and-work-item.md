# Curate — Cluster and File

## 1–2. Read and cluster

```text
yoke ouroboros field-note list --unreviewed --limit 50 --offset 0
```

Page; group by root cause; skip promoted entries.

## 3. Validate and propose

Verify named paths in current code and check existing items. Run only the
resolver for the selected output; these are alternatives
(`workflow.execution_instruction.resolve`, `--workflow dash` or `issue`):

```text
yoke workflow execution-instruction resolve --workflow dash --project {project} --full
```

Ask `create / skip / defer`.

## 4. Produce approved outputs

One instruction → Dash; agreed ACs → item.

```text
yoke ouroboros field-note promote {entry-id} --title "{specific title}" --instruction "{complete scope}"
yoke items create --title "{title}" --workflow issue --spec-file {spec_file} --project {project} --priority {priority} --entry-surface harness_skill --execution-instructions-considered
```

## 5. Review and archive

Tag the item's GitHub issue `source:ouroboros`. Skip deferred entries.

```text
yoke ouroboros entry mark-reviewed {id}
yoke ouroboros entry mark-archived --all-reviewed
```
