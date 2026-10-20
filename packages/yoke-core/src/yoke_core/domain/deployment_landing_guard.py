"""An open correction landing prevents release admission of an older landing."""

from yoke_core.domain.merge_queue_landing_attempt import read_open_attempt
from yoke_core.domain.project_identity import render_item_ref


def require_closed_landing(conn, item_id):
    attempt = read_open_attempt(conn, int(item_id))
    if attempt is not None:
        raise ValueError(
            f"item_landing_open: {render_item_ref(conn, int(item_id))} has open "
            f"correction pull request #{attempt['pr_number']}; wait for that "
            "landing to merge or close, then refresh the candidate and retry "
            "release enrollment and containment."
        )
