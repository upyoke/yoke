# Strategize — finalize

```text
yoke strategy carry mark --project <project> --state reflected --reason "<applied SML change identity>" --items <public-ref>
yoke strategy checkpoint record --project <project> --kind strategize
yoke events emit --name StrategizeCompleted --kind lifecycle --type strategize --source-type skill --severity STATUS --outcome completed --project <project> --context '<provenance-json>'
yoke claims work release --process STRATEGIZE --project <project> --reason completed
```

Record the checkpoint and release even when deferred. Put deferred changes in
the event context.
