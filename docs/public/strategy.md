# Strategy

The workbench **Strategy** tab shows the project's planning corpus. Authority
is the database (`strategy_docs` rows). Files under `.yoke/strategy/` are
gitignored local renders.

## Core documents

| Doc | Role |
|---|---|
| **MISSION** | One-line purpose |
| **LANDSCAPE** | External research and candidate imports |
| **VISION** | Chosen future state |
| **MASTER-PLAN** | Detailed evolving strategy |
| **CURRENT-PLAN** | Near-term focus (when present) |

Projects may add focused docs (for example area plans). Archive moves a doc
out of the active corpus without deleting history.

## How to author

Strategy is authored through a harness (`/yoke strategize`) with operator
checkpoints. The UI is for review and traceability.

```bash
yoke strategy doc list [--project P]
yoke strategy doc get <SLUG> [--project P]
yoke strategy render --target-root <checkout> [--project P]
# edit rendered files, then:
yoke strategy ingest <SLUG> --target-root <checkout> [--project P] --dry-run
```

## Link to frontier

`/yoke feed` maintains frontier dependency facts and can materialize new ideas
from strategy. Strategy without feed stays documentary; feed turns it into
runnable work pressure.
