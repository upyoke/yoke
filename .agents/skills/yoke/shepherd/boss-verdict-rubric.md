# Shepherd — Parse and Persist

Parse `VERDICT: READY|NOT_READY|CAVEATS`; else loose wording; else one
tool-less extraction; else NOT_READY `[UNPARSEABLE_BOSS_OUTPUT]`. Persist once:
```bash
yoke shepherd verdict --item ITEM --transition EDGE --worker WORKER --verdict VERDICT --caveats "{reason or numbered caveats}" --json
```
Dispose each caveat (RESOLVED only for an edit just made), then write
DEFERRED/ANALYZED under an EDGE heading in `shepherd_caveats` (`yoke items
structured-field section-upsert`) and in any task body a caveat names:
```bash
yoke shepherd caveat-disposition --item ITEM --transition EDGE --attempt {attempt} --caveat-num {caveat_num} --caveat-text "{caveat}" --disposition RESOLVED --resolution-details "{edit}" --verdict-id {verdict_id}
```
