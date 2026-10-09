"""What a Frontier card's delivery box says about how its item shipped.

Every fact here is read once for the whole set of drawn cards: a delivery box
is per card, but the releases it is compared against and the records it reads
are shared, so asking per card would re-read them once for every card drawn.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.item_overview_read import _dict_rows, _p


def card_delivery(
    conn: Any,
    drawn: list[dict[str, Any]],
    facts: dict[int, Any],
) -> dict[int, dict[str, Any]]:
    """Resolve flow environments and delivery summaries for drawn cards.

    Releases are resolved once per project, environment and completion flow.
    ``no_code_change`` is the item's own recorded delivery fact — execution
    evidence that attests the work changed no code — so a card can say so
    rather than leave a missing merge to be read as an unfinished one.
    """
    if not drawn:
        return {}
    from yoke_core.domain.dash_execution import DASH_EVIDENCE_SECTION
    from yoke_core.domain.item_json_sections import read_json_sections
    from yoke_core.domain.item_overview_effective_flow import apply_effective_flows
    from yoke_core.domain.release_delivery_summary import (
        DeliverySummary,
        ReleaseCandidates,
        delivery_summary,
        recorded_merge_shas_for_items,
    )

    apply_effective_flows(conn, drawn)
    flows = sorted(
        {
            str(row.get("completion_flow") or "").strip()
            for row in drawn
            if str(row.get("completion_flow") or "").strip()
        }
    )
    environment_by_flow: dict[str, Any] = {}
    if flows:
        marker = _p(conn)
        flow_placeholders = ", ".join(marker for _ in flows)
        flow_cursor = conn.execute(
            "SELECT df.id, df.target_environment_id, e.name AS environment "
            "FROM deployment_flows df LEFT JOIN environments e "
            "ON e.id=df.target_environment_id "
            f"WHERE df.id IN ({flow_placeholders})",
            tuple(flows),
        )
        flow_rows = _dict_rows(flow_cursor)
        names = {str(flow["id"]): flow["environment"] for flow in flow_rows}
        for row in drawn:
            row["completion_environment"] = names.get(str(row.get("completion_flow")))
        environment_by_flow = {
            str(flow["id"]): flow["target_environment_id"] for flow in flow_rows
        }
    ids = [int(row["internal_id"]) for row in drawn]
    from yoke_core.domain.completed_item_delivery import completed_deliveries

    completed = completed_deliveries(conn, ids)
    merges_by_item = recorded_merge_shas_for_items(conn, ids)
    evidence_by_item = read_json_sections(
        conn, item_ids=ids, section=DASH_EVIDENCE_SECTION
    )
    summaries: dict[int, dict[str, Any]] = {}
    by_release_line: dict[tuple[int, Any, str], Any] = {}
    for row in drawn:
        item_id = int(row["internal_id"])
        merges = merges_by_item.get(item_id, ())
        # Resolve release lines only for recorded landings.
        summary = DeliverySummary()
        if merges:
            flow = str(row.get("completion_flow") or "").strip()
            line = (
                int(facts[item_id]["project_id"]),
                environment_by_flow.get(flow),
                flow,
            )
            if line not in by_release_line:
                by_release_line[line] = ReleaseCandidates(
                    conn,
                    project_id=line[0],
                    environment_id=line[1],
                    flow=flow,
                )
            summary = delivery_summary(
                merges=merges,
                candidates=by_release_line[line],
                item_id=item_id,
            )
        evidence = evidence_by_item.get(item_id, {})
        summaries[item_id] = {
            "completed_deliveries": completed.get(item_id, []),
            "merges": summary.merges,
            "deployed": summary.deployed,
            "not_deployed": summary.not_deployed,
            # The flow of the release that carried a merge, which is what a
            # card with no flow of its own has to name instead.
            "flow": summary.flow,
            "no_code_change": evidence.get("no_changes") is True,
        }
    return summaries


__all__ = ["card_delivery"]
