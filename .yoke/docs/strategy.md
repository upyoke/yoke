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

## Link to items, and to a steering seat

An item belongs to one strategy document. That link is what a steering seat
covers: `yoke claims steering acquire --project P --doc SLUG` takes the seat
for one document and steers exactly the items linked to it, so two people
steer two documents in one project at once without either owning the whole
project. Acquiring with `--project` alone takes the whole-project seat
instead and locks no document.

Write the link either at intake or afterwards:

```bash
yoke dash "TITLE" "INSTRUCTION" --strategy-doc <SLUG> \
  --execution-instructions-considered
yoke strategy execution link PREFIX-N --slug <SLUG> --project P
```

For a Blitz the same link also names the document the item executes, and that
document's lock and the Blitz exclude each other. For every other workflow it
is membership only and gates nothing.

## Link to frontier

`/yoke feed` maintains frontier dependency facts and can materialize new ideas
from strategy. Strategy without feed stays documentary; feed turns it into
runnable work pressure.
