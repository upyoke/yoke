"""Render a named board snapshot without database access."""

import sys
from yoke_contracts.board.art import render_header, select_art
from yoke_contracts.board.data import BOARD_DATA_VERSION, BoardDataError, _decode_value
from yoke_contracts.board.item_data import ItemRow
from yoke_contracts.board.phase_timer import measure_phase
from yoke_contracts.board.renderer_dashboard import render_dashboard_data
from yoke_contracts.board.renderer_sections import render_item_sections
from yoke_contracts.board.sections import consistency_check, task_expanded_count
from yoke_contracts.board.session_data import render_session_rows
from yoke_contracts.board.architecture_data import render_architecture_rows
from yoke_contracts.board.timeline_data import render_timeline_rows
from yoke_contracts.project_contract.board_art.emoji import resolve_celebration


def render_board_from_payload(
    payload,
    *,
    scope,
    config,
    art_config,
    seed=None,
    repo_root=None,
    vision_entries=None,
    phase_recorder=None,
) -> str:
    """Compose server facts with client-local artwork and VISION labels."""
    if payload.get("version") != BOARD_DATA_VERSION:
        raise BoardDataError(
            f"board data contract {payload.get('version')!r} does not match "
            f"renderer contract {BOARD_DATA_VERSION}"
        )
    data = _decode_value(payload)
    buckets = {
        key: [
            ItemRow(
                **{
                    **dict(epic_id=None, updated_at=None),
                    **{k: v for k, v in row.items() if k in ItemRow._fields},
                }
            )
            for row in rows
        ]
        for key, rows in data["items"].items()
    }
    counts = {epic["id"]: epic["task_count"] for epic in data["epics"]}
    tasks = {
        epic["id"]: [
            (row["id"], row["title"], row["status"], row.get("status_glyph"))
            for row in epic["tasks"]
        ]
        for epic in data["epics"]
    }
    section_stats = {
        key: task_expanded_count(buckets.get(key, []), counts)
        for key in ("active", "pipeline", "backlog", "blocked", "done")
    }
    section_stats["frozen"] = task_expanded_count(buckets.get("freezer", []), counts)
    total = sum(section_stats.values()) + task_expanded_count(
        buckets.get("unknown", []), counts
    )
    mode, variant = select_art(config, art_config, seed)
    celebration = resolve_celebration(section_stats, mode, seed)
    with measure_phase(phase_recorder, "header_render"):
        header = render_header(
            None,
            config,
            art_config,
            mode,
            variant,
            data["frontier"],
            stats_counts=section_stats,
            stats_total=min(total, config.dashboard_meter_cap),
            seed=seed,
            celebration=celebration,
        )
    lines = [header] if header else []
    with measure_phase(phase_recorder, "dashboard"):
        lines.extend(render_dashboard_data(data["dashboard"]))
    with measure_phase(phase_recorder, "zen"):
        timeline = render_timeline_rows(
            data["timeline"], vision_entries or [], data.get("vision_project")
        )
    if timeline:
        lines.extend(["", *timeline])
    with measure_phase(phase_recorder, "sessions"):
        sessions = render_session_rows(
            data["sessions"]["active"],
            data["sessions"]["recent"],
            show_recent=config.dashboard_recent_sessions,
        )
    if sessions:
        lines.extend(["", sessions])
    with measure_phase(phase_recorder, "architecture"):
        architecture = render_architecture_rows(data["architecture"])
    if architecture:
        lines.extend(["", architecture])
    expected = 0
    if any(buckets.values()):
        section_lines, expected = render_item_sections(
            config,
            buckets,
            counts,
            tasks,
            data["max_id_width"],
            phase_recorder,
            celebration,
        )
        lines.extend(["", *section_lines])
    else:
        lines.extend(["*No backlog items yet. Create one with `/yoke idea`.*", ""])
    content = "\n".join(lines)
    with measure_phase(phase_recorder, "consistency_check"):
        ok, message = consistency_check(expected, content)
    if not ok:
        print(message, file=sys.stderr)
    return content
