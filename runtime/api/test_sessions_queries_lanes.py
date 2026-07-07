"""Lane filtering and supported_paths tests for session_offer_with_ownership.

Split from ``test_sessions_queries.py``. Covers lane allowed-paths filtering,
supported_paths plumbing, and Codex manifest overrides.
"""

from __future__ import annotations

import json
import os

from runtime.api.test_sessions import (
    conn,  # noqa: F401 — fixture import
    ownership_conn,  # noqa: F401 — fixture import
    _ensure_active_session,
)
from yoke_core.domain.sessions import (
    session_offer_with_ownership,
)


class TestSessionOfferLanes:
    """Lane-filter + path-compatibility tests for session_offer_with_ownership."""

    def test_claim_race_retries_next_candidate(self, ownership_conn):
        """AC-7: lost claim race retries with next candidate."""
        conn, ws = ownership_conn
        _ensure_active_session(conn, "sess-race-1", ws, executor="A", model="opus")
        _ensure_active_session(conn, "sess-race-2", ws, executor="B", model="opus")
        # Add a second runnable item
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id,
                project_sequence, created_at, updated_at, source, frozen)
               VALUES (101, 'Second item', 'issue', 'refined-idea', 'high',
                       1, 101, '2026-03-01', '2026-03-01', 'user', 0)"""
        )
        conn.commit()

        # First session claims
        r1 = session_offer_with_ownership(
            conn, session_id="sess-race-1", executor="A",
            provider="anthropic", model="opus", workspace=ws,
        )
        assert r1["action_hint"] == "charge"
        first_claimed = r1["new_claim"]["item_id"]

        # Second session should get the other item
        r2 = session_offer_with_ownership(
            conn, session_id="sess-race-2", executor="B",
            provider="anthropic", model="opus", workspace=ws,
        )
        assert r2["action_hint"] == "charge"
        second_claimed = r2["new_claim"]["item_id"]
        assert first_claimed != second_claimed

    def test_offer_prefers_compatible_lower_ranked_item(self, ownership_conn):
        """Lane/path compatibility filtering happens before claim selection.

        Regression for the Codex ALTMAN failure mode: a globally higher-ranked
        DARIUS-only ADVANCE item must not mask a lower-ranked but compatible
        ALTMAN REFINE item.
        """
        conn, ws = ownership_conn
        _ensure_active_session(
            conn,
            "sess-altman-compatible",
            ws,
            executor="codex",
            provider="openai",
            model="gpt-5.4",
            execution_lane="ALTMAN",
        )
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id,
                project_sequence, created_at, updated_at, source, frozen, spec)
               VALUES (101, 'Compatible refine item', 'issue', 'idea', 'high',
                       1, 101, '2026-03-01', '2026-03-01', 'user', 0,
                       '# Compatible refine item\n\nFixture spec body for lane tests.')"""
        )
        conn.commit()

        result = session_offer_with_ownership(
            conn,
            session_id="sess-altman-compatible",
            executor="codex",
            provider="openai",
            model="gpt-5.4",
            workspace=ws,
            execution_lane="ALTMAN",
            supported_paths=["refine", "polish"],
            lane_allowed_paths={
                "DARIUS": ["advance", "conduct", "shepherd", "usher"],
                "ALTMAN": ["refine", "polish"],
            },
        )

        assert result["action_hint"] == "charge"
        assert result["new_claim"] is not None
        assert result["new_claim"]["item_id"] == 101
        assert result["schedule_result"].selected_step is not None
        assert result["schedule_result"].selected_step.item_id == "YOK-101"
        assert [step.item_id for step in result["schedule_result"].ranked_steps] == ["YOK-101"]

    def test_offer_returns_no_work_when_no_compatible_item_exists(self, ownership_conn):
        """Incompatible runnable work is filtered out for the current lane."""
        conn, ws = ownership_conn
        _ensure_active_session(
            conn,
            "sess-altman-none",
            ws,
            executor="codex",
            provider="openai",
            model="gpt-5.4",
            execution_lane="ALTMAN",
        )
        result = session_offer_with_ownership(
            conn,
            session_id="sess-altman-none",
            executor="codex",
            provider="openai",
            model="gpt-5.4",
            workspace=ws,
            execution_lane="ALTMAN",
            supported_paths=["refine", "polish"],
            lane_allowed_paths={
                "DARIUS": ["advance", "conduct", "shepherd", "usher"],
                "ALTMAN": ["refine", "polish"],
            },
        )

        assert result["action_hint"] == "no_work"
        assert result["new_claim"] is None
        assert result["schedule_result"].selected_step is None
        assert result["schedule_result"].ranked_steps == []

    def test_unknown_lane_is_filtered_before_offer_time_claim(self, ownership_conn):
        """unknown lanes must not claim work before WAIT/no-work."""
        conn, ws = ownership_conn
        _ensure_active_session(
            conn,
            "sess-unknown-lane",
            ws,
            executor="codex",
            provider="openai",
            model="gpt-5.4",
            execution_lane="primary",
        )
        result = session_offer_with_ownership(
            conn,
            session_id="sess-unknown-lane",
            executor="codex",
            provider="openai",
            model="gpt-5.4",
            workspace=ws,
            execution_lane="primary",
            lane_allowed_paths={
                "DARIUS": ["advance", "conduct", "shepherd", "usher"],
                "ALTMAN": ["refine", "polish"],
            },
        )

        assert result["action_hint"] == "no_work"
        assert result["new_claim"] is None
        schedule = result["schedule_result"]
        assert schedule.selected_step is None
        assert schedule.ranked_steps == []
        assert schedule.lane_filtered_count >= 1

    def test_offer_preserves_lane_filtered_detail_when_all_work_incompatible(self, ownership_conn):
        """AC-4/AC-5/AC-6: when the offer's lane filters out every runnable item,
        the schedule preserves the dropped steps on lane_filtered_items with
        full structured detail (item_id, title, status, next_step,
        required_path, rank, claim_state), and routing the
        schedule through the decision engine yields WAIT with
        wait_reason=no_lane_compatible_work — NOT a silent FEED, and not
        an ESCALATE that sounds like the system is broken."""
        from yoke_core.domain.session import (
            ActionKind, SessionOffer, decide_next_action,
        )
        from yoke_core.api.service_client_sessions import (
            _build_frontier_state_from_schedule,
        )

        conn, ws = ownership_conn
        _ensure_active_session(
            conn,
            "sess-lane-mismatch",
            ws,
            executor="codex",
            provider="openai",
            model="gpt-5.4",
            execution_lane="ALTMAN",
        )
        # Fixture already seeded item 100 at refined-idea (issue). The
        # refined-idea issue status routes to `advance`, a DARIUS-only path.
        # An ALTMAN session with supported_paths=refine,polish filters it out.
        lane_allowed = {
            "DARIUS": ["advance", "conduct", "shepherd", "usher"],
            "ALTMAN": ["refine", "polish"],
        }
        result = session_offer_with_ownership(
            conn,
            session_id="sess-lane-mismatch",
            executor="codex",
            provider="openai",
            model="gpt-5.4",
            workspace=ws,
            execution_lane="ALTMAN",
            supported_paths=["refine", "polish"],
            lane_allowed_paths=lane_allowed,
        )

        schedule = result["schedule_result"]
        assert schedule is not None
        # Filter preserved the dropped step (no scheduler ranking changes)
        assert schedule.lane_filtered_count >= 1
        assert len(schedule.lane_filtered_items) == schedule.lane_filtered_count
        filtered = schedule.lane_filtered_items[0]
        expected_item_ref = f"YOK-{100}"
        for key in (
            "item_id", "title", "status", "next_step", "required_path",
            "rank", "claim_state",
        ):
            assert key in filtered, f"lane_filtered_items missing key: {key}"
        assert filtered["item_id"] == expected_item_ref
        # The refined-idea issue requires advance, which is DARIUS-only
        assert filtered["required_path"] == "advance"

        # Routing the schedule through the decision engine must produce the
        # filtered-empty WAIT — not a silent FEED, and not a misleading ESCALATE.
        offer = SessionOffer(
            session_id="sess-lane-mismatch",
            executor="codex",
            provider="openai",
            model="gpt-5.4",
            workspace=ws,
            execution_lane="ALTMAN",
            supported_paths=["refine", "polish"],
        )
        frontier = _build_frontier_state_from_schedule(schedule)
        action = decide_next_action(
            offer, frontier, active_claims=None,
            lane_allowed_paths=lane_allowed,
        )
        # Lane-mismatched frontier waits, does not feed or escalate
        assert action.action == ActionKind.WAIT, (
            "Silent FEED / misleading ESCALATE regression: lane-filtered frontier "
            "must WAIT with no_lane_compatible_work"
        )
        assert action.context["wait_reason"] == "no_lane_compatible_work"
        # The filtered-empty WAIT context carries actual_lane,
        # lane_filtered_count, lane_filtered_note, lane_filtered_items, and a
        # compact lane_filtered_paths view.
        assert action.context["actual_lane"] == "ALTMAN"
        assert action.context["lane_filtered_count"] >= 1
        assert "lane_filtered_note" in action.context
        assert "lane_filtered_items" in action.context
        assert action.context["lane_filtered_items"][0]["item_id"] == expected_item_ref
        paths = action.context["lane_filtered_paths"]
        assert paths, "lane_filtered_paths must summarize at least one path"
        for entry in paths:
            for key in ("required_path", "count"):
                assert key in entry, f"lane_filtered_paths entry missing {key}"

    def test_supported_paths_in_return_dict(self, ownership_conn):
        """AC-6: supported_paths from the offer is returned in the result dict."""
        conn, ws = ownership_conn
        _ensure_active_session(conn, "sess-paths-1", ws, model="opus")
        result = session_offer_with_ownership(
            conn,
            session_id="sess-paths-1",
            executor="DARIUS",
            provider="anthropic",
            model="opus",
            workspace=ws,
            supported_paths=["shepherd", "advance"],
        )
        assert result["supported_paths"] == ["shepherd", "advance"]

    def test_supported_paths_defaults_to_empty(self, ownership_conn):
        """AC-6: supported_paths defaults to empty list when not provided."""
        conn, ws = ownership_conn
        _ensure_active_session(conn, "sess-paths-2", ws, model="opus")
        result = session_offer_with_ownership(
            conn,
            session_id="sess-paths-2",
            executor="DARIUS",
            provider="anthropic",
            model="opus",
            workspace=ws,
        )
        assert result["supported_paths"] == []

    def test_codex_manifest_limits_override_offer_input(self, ownership_conn):
        """AC-4/AC-5: shared registry plus limitations override caller paths."""
        conn, ws = ownership_conn
        _ensure_active_session(
            conn,
            "sess-manifest-truth",
            ws,
            executor="codex",
            provider="openai",
            model="gpt-5.4",
            execution_lane="ALTMAN",
        )
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id,
                project_sequence, created_at, updated_at, source, frozen, spec)
               VALUES (101, 'Compatible refine item', 'issue', 'idea', 'high',
                       1, 101, '2026-03-01', '2026-03-01', 'user', 0,
                       '# Compatible refine item\n\nFixture spec body for lane tests.')"""
        )
        conn.commit()

        manifest_dir = os.path.join(ws, "runtime", "harness", "codex")
        os.makedirs(manifest_dir, exist_ok=True)
        with open(os.path.join(manifest_dir, "manifest.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "supports": {
                        "command_source": "shared_yoke_registry",
                        "disabled_downstream_paths": [
                            "shepherd",
                            "advance",
                            "polish",
                            "usher",
                        ],
                    }
                },
                handle,
            )

        result = session_offer_with_ownership(
            conn,
            session_id="sess-manifest-truth",
            executor="codex",
            provider="openai",
            model="gpt-5.4",
            workspace=ws,
            supported_paths=["advance"],
        )

        assert result["supported_paths"] == ["refine"]
        assert result["action_hint"] == "charge"
        assert result["new_claim"] is not None
        assert result["new_claim"]["item_id"] == 101
