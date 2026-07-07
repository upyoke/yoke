# Board Renderer Package (`runtime/api/board/`)

Python package that renders `BOARD.md` from Yoke board data payloads. This is the hot path for all board rebuilds. Operators invoke it via `yoke board rebuild`, which composes a transport-safe `board.data.get` fetch with `render_board_from_payload(...)`, then writes the project-local `.yoke/BOARD.md` under the existing lock. For terminal output, use `yoke board rebuild --print` or `yoke board rebuild --print-only`.

## Architecture

The board renderer is the sole owner of all rendering logic. Legacy shell rendering helpers were retired during the zero-shell work; their semantics are fully covered by the Python modules below and by `yoke_core.domain.rebuild_board`.

```
yoke board rebuild
    |
    +-- yoke_core.domain.rebuild_board.rebuild()   # Orchestrator (throttle, lock, file I/O)
            |
            +-- board.data.get                       # Server-side recorded query plan
            |
            +-- yoke_core.board.renderer.render_board_from_payload()
                    |
                    +-- db.py         # Postgres reads (items, epic_tasks, events)
                    +-- config.py     # Settings parser (dashboard, timeline, art weights, etc.)
                    +-- art.py        # Master map, art variants, header rendering
                    +-- widgets.py    # Dashboard widgets (velocity, weather, age, badges)
                    +-- sections.py   # Board sections (Active, Pipeline, Backlog, etc.)
                    +-- zen.py        # Project timelines widget
                    +-- renderer.py   # Top-level assembly (composes all components)
                    +-- __main__.py   # Preview-only development CLI
```

## Modules

| Module | Purpose |
|--------|---------|
| `db.py` | `BoardDB` class: Postgres read queries for items, epic tasks, and event data. All renderer DB access is centralized here. |
| `config.py` | `BoardConfig` dataclass and `parse_config()`: reads project-local `.yoke/board.json` renderer settings. |
| `art.py` | `ArtConfig`, `ArtVariant`, art selection, master map parsing, header rendering. Reads art variants (emoji, ASCII, mixed) from project-local `.yoke/board-art`. Supports frontier fill, rainbow modes (5 sub-modes), and standalone variant display. Stats box rendering with 10-cell proportional meters. |
| `widgets.py` | Dashboard widget renderers: velocity sparkline (14-day touched-units), 120-day velocity meter, weather heuristic, type badges, age heatmap, achievement badges. |
| `sections.py` | Board section classification (Active, Pipeline, Backlog, Freezer, Done), item row rendering, epic sub-row expansion, frontier counting, consistency checks. |
| `zen.py` | Project timelines widget: per-project pathway lines with feature dots, temporal zones, vision labels. Queries items table and VISION.md. |
| `renderer.py` | `render_board_from_payload()`: top-level assembly path used by `yoke board rebuild`; `render_board()` remains an in-process test/helper path. |
| `__main__.py` | Preview-only development CLI for art/widget visual QA. Full board output uses `yoke board rebuild --print` or `--print-only`. |

## CLI Usage

### Full Board Render

Use the canonical Yoke CLI:

```bash
yoke board rebuild --print
yoke board rebuild --print-only
```

Options:
- `--print`: rebuild `.yoke/BOARD.md`, then print the generated board markdown to stdout
- `--print-only`: render the same BOARD.md text to stdout without writing `.yoke/BOARD.md` or its timestamp
- `--no-pager`: disable pagination; write the board straight to stdout
- `--scope`: optional project scope (`all` or a specific project name)
- `--repo-root`: optional checkout root override
- `--output-name`: optional output filename override for write mode

Both print modes paginate like `git`: when stdout is an interactive
terminal the board is piped through a pager (`YOKE_PAGER` → `PAGER` →
`less`, with `LESS=FRX` when unset so short boards skip the pager).
Piped/redirected output and non-interactive callers (including the agent
Bash tool) write straight through unpaged. Use `--no-pager`, or set
`YOKE_PAGER`/`PAGER` to empty or `cat`, to disable paging. Pagination
is owned by `packages/yoke-cli/src/yoke_cli/terminal_pager.py`.

### Preview Mode

Used directly by operators for visual QA without a database:

```bash
python3 -m yoke_core.board preview --repo-root /path/to/project --rainbow
python3 -m yoke_core.board preview --repo-root /path/to/project --done 5 --active 2 --total 10
python3 -m yoke_core.board preview --all --dashboard --velocity-meter
python3 -m yoke_core.board preview --repo-root /path/to/project --zen
```

Preview supports all art modes: rainbow (5 sub-modes), frontier/progress, emoji/ASCII/mixed variants, and `--all` for side-by-side comparison.

## Testing

```bash
# All board renderer tests:
python3 -m yoke_core.tools.watch_pytest -- runtime/api/board/tests runtime/api/test_board_art.py runtime/api/test_board_scaffold.py -v

# Individual test modules:
python3 -m yoke_core.tools.watch_pytest -- runtime/api/board/tests/test_renderer.py -v  # Renderer assembly
python3 -m yoke_core.tools.watch_pytest -- runtime/api/board/tests/test_sections.py -v  # Section classification
python3 -m yoke_core.tools.watch_pytest -- runtime/api/board/tests/test_widgets.py -v   # Dashboard widgets
python3 -m yoke_core.tools.watch_pytest -- runtime/api/board/tests/test_zen.py -v       # Project timelines
```

## Relationship to Other Surfaces

| Component | Normal rebuild path | Preview path |
|-----------|---------------------|--------------|
| `yoke_core.domain.rebuild_board.rebuild()` | Orchestrator (throttle, lock, file write). Called by `yoke board rebuild`. | Not used |
| `yoke_core.board.renderer` | Renders full board content from the `board.data.get` payload | Supplies art/widget helpers used by preview |
| `python3 -m yoke_core.board preview` | Not used | Renders all preview modes, including `--zen` when a DB is available |
