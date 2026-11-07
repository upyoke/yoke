# Implement — activation refusals

An unmet activation gate means do not start or staff yet. An integration
gate lets you work, test and open the pull request now; merge only after it
clears. A closure gate lets you work and merge now; close only after it
clears. Park only at the step the unmet gate holds.

Report a blocked claim or diverged ref; the owner reconciles without losing
commits. An independent overlap is recorded by this session per
[agent rules](../../../../.yoke/docs/agents/rules.md#coordination),
source `implement`. Operator rerun:

```text
yoke claims path activation-run --item PREFIX-N
```
