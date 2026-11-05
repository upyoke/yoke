"""Name question askers from their current holdings with page-wide reads."""

from collections import defaultdict

from yoke_core.domain.actor_render import actor_display_labels
from yoke_core.domain.coordination_claim_keys import (
    COORDINATION_TARGET_KINDS,
    key_for_target,
)
from yoke_core.domain.sessions_holdings_claim_facts import (
    claimed_item_facts,
    param_marker,
)
from yoke_core.domain.sessions_holdings_claim_rows import active_claim_rows
from yoke_core.domain.work_claim_targets import from_row


def requester_labels(conn, session_ids) -> dict[str, str]:
    """Compose labels once for all asking sessions on a page."""
    ids = tuple(dict.fromkeys(session_ids))
    if not ids:
        return {}
    marker = param_marker(conn)
    markers = ', '.join(marker for _ in ids)
    sessions = conn.execute(
        "SELECT s.session_id, s.actor_id, s.executor, "
        "(SELECT sr.hostname FROM session_relays sr "
        "WHERE sr.machine_id=s.machine_id AND sr.hostname IS NOT NULL "
        "ORDER BY sr.last_seen_at DESC LIMIT 1) AS hostname "
        f"FROM harness_sessions s WHERE s.session_id IN ({markers})",
        ids,
    ).fetchall()
    claims = [dict(row) for row in active_claim_rows(conn, ids)]
    targets = [(row['session_id'], from_row(row)) for row in claims]
    item_ids = list(dict.fromkeys(
        target.item_id if target.kind == 'item' else target.epic_id
        for _, target in targets if target.kind in {'item', 'epic_task'}
    ))
    items = claimed_item_facts(conn, item_ids)
    project_ids = tuple(dict.fromkeys(
        target.project_id for _, target in targets if target.kind == 'steering'
    ))
    projects = {}
    if project_ids:
        markers = ', '.join(marker for _ in project_ids)
        projects = {row['id']: row['slug'] for row in conn.execute(
            f"SELECT id, slug FROM projects WHERE id IN ({markers})", project_ids
        ).fetchall()}
    actors = actor_display_labels(conn, [row['actor_id'] for row in sessions])
    seats, locks, work = defaultdict(list), defaultdict(list), defaultdict(list)
    for session_id, target in targets:
        if target.kind == 'steering':
            project = projects.get(target.project_id, 'project unavailable')
            seats[session_id].append(
                f'{target.document} in {project}' if target.document else project
            )
        elif target.kind in COORDINATION_TARGET_KINDS:
            locks[session_id].append(key_for_target(target))
        elif target.kind in {'item', 'epic_task'}:
            facts = items.get(target.item_id or target.epic_id, {})
            ref = facts.get('public_ref', 'item unavailable')
            work[session_id].append(
                f'{ref} task {target.task_num}' if target.kind == 'epic_task'
                else f"{ref} ({facts['item_title']})" if facts.get('item_title')
                else ref
            )
    labels = {}
    for row in sessions:
        session_id = row['session_id']
        groups = []
        if seats[session_id]:
            groups.append('steering seat for ' + ' and '.join(seats[session_id]))
        for holdings in (locks, work):
            if holdings[session_id]:
                groups.append(' and '.join(holdings[session_id]))
        if not groups:
            harness = row['executor'] or 'harness unavailable'
            groups.append(harness + (f" on {row['hostname']}" if row['hostname'] else ''))
        labels[session_id] = ' · '.join([
            actors.get(row['actor_id'], 'person unavailable'), *groups
        ])
    return labels
