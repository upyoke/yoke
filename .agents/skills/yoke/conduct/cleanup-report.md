# Conduct — every exit

```text
git -C {MAIN_ROOT} log origin/main..main --oneline
```

Report unpushed main commits; never stage `.yoke/BOARD.md`. Print
`CONDUCT_RESULT: SUCCESS|HALTED`, each task's state and attempts, failed,
blocked and not-started tasks, and the next action. --no-chain or bypass
SUCCESS is not parent completion. A halt checkpoints the Progress Log first.
