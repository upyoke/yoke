# Wrapup — Record and Close

1. One feedback note per observation; use failed, new, unclear, observation or idea:

   ```text
   yoke feedback --to universe --category "{category}" --evidence "{project observation}"
   yoke feedback --to yoke --category failed --evidence "{Yoke problem}"
   ```

2. Ask before filing each follow-up through `/yoke idea`.
3. Checkpoint each unfinished item while holding its claim, before any release;
   skip terminal items. Live release-wait claims stay with their owning skill:

   ```text
   yoke items progress-log append PREFIX-N --headline "Session checkpoint" --content "{objective, blockers, next action, evidence}" --source wrapup
   ```

4. Summarize and commit authored artifacts.
