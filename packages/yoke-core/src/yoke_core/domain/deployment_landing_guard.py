"""An open correction landing prevents release admission of an older landing."""

from yoke_core.domain.merge_queue_landing_attempt import read_open_attempts
from yoke_core.domain.item_ref_render import render_item_ref_lookup


def open_landing_refusals(conn, item_ids):
    attempts = read_open_attempts(conn, item_ids)
    if not attempts:
        return {}
    ref = render_item_ref_lookup(conn, attempts)
    return {
        item_id: (
            f"item_landing_open: {ref(item_id)} has open correction pull request "
            f"#{attempt['pr_number']}; wait for that landing to merge or close, "
            "then refresh the candidate and retry release enrollment and containment."
        )
        for item_id, attempt in attempts.items()
    }


def require_closed_landings(conn, item_ids):
    refusals = open_landing_refusals(conn, item_ids)
    if refusals:
        raise ValueError(refusals[min(refusals)])


def require_closed_landing(conn, item_id):
    require_closed_landings(conn, (int(item_id),))
