# Feed — Enter

```text
yoke claims work acquire --process FEED --project <project> --reason feed_run
yoke events emit --name FeedStarted --kind lifecycle --type feed --source-type skill --severity STATUS --outcome started --project <project>
```

Every exit after acquiring releases FEED (`yoke claims work release
--process FEED`). Next: [gather.md](gather.md).
