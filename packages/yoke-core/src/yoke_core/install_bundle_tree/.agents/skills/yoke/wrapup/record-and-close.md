# Wrapup — Record and Close

1. One entry per observation (problem, friction, idea, cross-critique,
   metric, pattern):

   ```text
   yoke ouroboros entry insert --stdin --timestamp "{UTC ISO 8601}" --agent conduct --context wrapup --category "{category}"
   ```

2. Ask before filing each follow-up through `/yoke idea`.
3. Checkpoint each unfinished item while holding its claim, before any release;
   skip terminal items. Live release-wait claims stay with their owning skill:

   ```text
   yoke items progress-log append PREFIX-N --headline "Session checkpoint" --content "{objective, blockers, next action, evidence}" --source wrapup
   ```

4. Summarize and commit authored artifacts.
