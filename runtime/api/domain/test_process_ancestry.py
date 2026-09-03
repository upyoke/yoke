"""Unit tests for the portable process-ancestry walk.

All process-table access is injected (``parents`` maps and ``name_of`` /
``start_time_of`` callables), so no test spawns ``ps`` or depends on the
live process tree.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from yoke_contracts import process_ancestry
from yoke_contracts.process_ancestry import (
    ProcessAnchor,
    ancestor_pids,
    anchor_candidate_pids,
    find_nearest_harness_anchor,
    find_nearest_named_process_anchor,
    is_harness_process_name,
    is_multiplexed_process_name,
    parent_map,
    process_table,
)


# Synthetic process tree:
#   1 (launchd) -> 100 (Claude desktop shell) -> 200 (claude agent binary)
#   -> 300 (zsh) -> 400 (python hook)
_TREE = {400: 300, 300: 200, 200: 100, 100: 1}
_NAMES = {
    400: "python3",
    300: "zsh",
    200: "claude",
    100: "Claude",
}
_STARTS = {
    400: "Wed Jun 10 14:23:10 2026",
    300: "Wed Jun 10 14:23:09 2026",
    200: "Wed Jun 10 14:05:41 2026",
    100: "Tue Jun  9 16:27:28 2026",
}


class TestAncestorPids(unittest.TestCase):
    def test_walks_nearest_first_to_root(self):
        self.assertEqual(
            ancestor_pids(400, parents=_TREE),
            [300, 200, 100, 1],
        )

    def test_stops_on_missing_parent(self):
        self.assertEqual(ancestor_pids(400, parents={400: 300}), [300])

    def test_stops_on_cycle(self):
        cyclic = {400: 300, 300: 400}
        self.assertEqual(ancestor_pids(400, parents=cyclic), [300])

    def test_unknown_pid_yields_empty(self):
        self.assertEqual(ancestor_pids(999, parents=_TREE), [])


class TestHarnessNameMatcher(unittest.TestCase):
    def test_matches_claude_binary_case_insensitively(self):
        self.assertTrue(is_harness_process_name("claude"))
        self.assertTrue(is_harness_process_name("Claude"))
        self.assertTrue(is_harness_process_name("claude-code"))

    def test_rejects_non_harness_names(self):
        for name in ("zsh", "python3", "node", "disclaimer", "", None):
            self.assertFalse(is_harness_process_name(name))


class TestMultiplexedNameMatcher(unittest.TestCase):
    def test_matches_session_hosting_processes(self):
        self.assertTrue(is_multiplexed_process_name("codex"))
        self.assertTrue(is_multiplexed_process_name("Codex"))
        self.assertTrue(is_multiplexed_process_name("codex-code-mode-host"))

    def test_accepts_claude_background_pool_process_titles(self):
        """The daemon hands one pooled process to worker after worker, so its
        pid names a pool slot rather than any single session."""
        self.assertTrue(is_multiplexed_process_name("claude bg-spare"))
        self.assertTrue(is_multiplexed_process_name("claude bg-pty-host"))

    def test_rejects_per_session_and_unrelated_names(self):
        for name in ("claude", "zsh", "python3", "", None):
            self.assertFalse(is_multiplexed_process_name(name))


class TestAnchorCandidatePids(unittest.TestCase):
    def test_full_chain_when_no_hosting_process_intervenes(self):
        self.assertEqual(
            anchor_candidate_pids(400, parents=_TREE, name_of=_NAMES.get),
            [300, 200, 100, 1],
        )

    def test_chain_ends_at_the_hosting_process(self):
        names = {300: "zsh", 200: "cursor-agent", 100: "claude"}
        self.assertEqual(
            anchor_candidate_pids(400, parents=_TREE, name_of=names.get),
            [300],
        )

    def test_chain_stops_before_a_claude_above_the_background_pool(self):
        """A launched worker's chain can rise into an ordinary per-session
        claude; walking through it would resolve to that session's id."""
        names = {300: "zsh", 200: "claude bg-spare", 100: "claude"}
        self.assertEqual(
            anchor_candidate_pids(400, parents=_TREE, name_of=names.get),
            [300],
        )

    def test_injected_tree_without_names_classifies_nothing(self):
        # ``parents`` and ``name_of`` describe one table; reading live
        # names against a synthetic tree would decide by coincidence.
        self.assertEqual(
            anchor_candidate_pids(400, parents=_TREE),
            [300, 200, 100, 1],
        )

    def test_both_process_facts_come_from_one_ps_call(self):
        rows = [
            "  400   300 python3",
            "  300   200 zsh",
            "  200     1 cursor-agent",
        ]
        with patch.object(
            process_ancestry,
            "ps_lines",
            return_value=rows,
        ) as ps_lines:
            self.assertEqual(anchor_candidate_pids(400), [300])
        self.assertEqual(ps_lines.call_count, 1)


class TestFindNearestHarnessAnchor(unittest.TestCase):
    def test_finds_per_session_agent_binary_not_desktop_shell(self):
        anchor = find_nearest_harness_anchor(
            400,
            parents=_TREE,
            name_of=_NAMES.get,
            start_time_of=_STARTS.get,
        )
        assert anchor is not None
        # Nearest-first: the per-session agent binary (200), never the
        # shared desktop shell (100) above it.
        self.assertEqual(anchor.pid, 200)
        self.assertEqual(anchor.start_time, _STARTS[200])
        self.assertEqual(anchor.process_name, "claude")


class TestFindNearestNamedProcessAnchor(unittest.TestCase):
    def test_liveness_walk_can_select_an_explicit_multiplexed_host(self):
        names = {300: "zsh", 200: "cursor-agent", 100: "claude"}
        anchor = find_nearest_named_process_anchor(
            ("cursor-agent", "cursor"),
            400,
            parents=_TREE,
            name_of=names.get,
            start_time_of=_STARTS.get,
        )
        assert anchor == ProcessAnchor(
            pid=200,
            start_time=_STARTS[200],
            process_name="cursor-agent",
        )

    def test_liveness_walk_refuses_a_match_without_start_time(self):
        anchor = find_nearest_named_process_anchor(
            ("cursor-agent",),
            400,
            parents=_TREE,
            name_of={300: "zsh", 200: "cursor-agent"}.get,
            start_time_of=lambda _pid: None,
        )
        self.assertIsNone(anchor)

    def test_returns_none_for_operator_terminal(self):
        names = {300: "zsh", 200: "Terminal", 100: "launchd"}
        anchor = find_nearest_harness_anchor(
            400,
            parents=_TREE,
            name_of=names.get,
            start_time_of=_STARTS.get,
        )
        self.assertIsNone(anchor)

    def test_returns_none_when_start_time_unavailable(self):
        anchor = find_nearest_harness_anchor(
            400,
            parents=_TREE,
            name_of=_NAMES.get,
            start_time_of=lambda _pid: None,
        )
        self.assertIsNone(anchor)

    def test_session_hosting_process_is_never_an_anchor(self):
        # One process hosting every conversation: anchoring to it would give
        # each sibling whichever session wrote the registry record last.
        names = {300: "zsh", 200: "codex", 100: "launchd"}
        anchor = find_nearest_harness_anchor(
            400,
            parents=_TREE,
            name_of=names.get,
            start_time_of=_STARTS.get,
        )
        self.assertIsNone(anchor)

    def test_walk_stops_at_the_hosting_process(self):
        # A real per-session binary above the multiplexer must not be reached:
        # the calling process is inside the shared host, not that session.
        names = {300: "zsh", 200: "codex-code-mode-host", 100: "claude"}
        anchor = find_nearest_harness_anchor(
            400,
            parents=_TREE,
            name_of=names.get,
            start_time_of=_STARTS.get,
        )
        self.assertIsNone(anchor)

    def test_per_session_binary_below_a_hosting_process_still_resolves(self):
        # Nearest-first still wins: the multiplexer is only reached when no
        # per-session binary sits between it and the caller.
        names = {300: "claude", 200: "codex", 100: "launchd"}
        anchor = find_nearest_harness_anchor(
            400,
            parents=_TREE,
            name_of=names.get,
            start_time_of=_STARTS.get,
        )
        assert anchor is not None
        self.assertEqual(anchor.pid, 300)

    def test_full_path_comm_is_basenamed(self):
        names = dict(_NAMES)
        names[200] = (
            "/Users/op/Library/Application Support/Claude/claude-code/"
            "2.1.170/claude.app/Contents/MacOS/claude"
        )
        with patch.object(
            process_ancestry,
            "process_command_name",
            side_effect=lambda pid: names.get(pid),
        ):
            anchor = find_nearest_harness_anchor(
                400,
                parents=_TREE,
                start_time_of=_STARTS.get,
            )
        assert anchor is not None
        self.assertEqual(anchor.pid, 200)
        self.assertEqual(anchor.process_name, "claude")


class TestPsParsing(unittest.TestCase):
    def test_parent_map_parses_pid_ppid_pairs(self):
        with patch.object(
            process_ancestry,
            "ps_lines",
            return_value=["    1     0", "  338     1", "garbage line x"],
        ):
            parents = parent_map()
        self.assertEqual(parents, {1: 0, 338: 1})

    def test_process_table_keeps_a_path_with_spaces_whole(self):
        rows = ["  200     1 /Applications/My App/Contents/MacOS/claude"]
        with patch.object(process_ancestry, "ps_lines", return_value=rows):
            self.assertEqual(process_table(), {200: (1, "claude")})

    def test_process_table_tolerates_a_missing_command_name(self):
        # A nameless process must still carry its parent link, or the walk
        # breaks at it and every ancestor above becomes unreachable.
        with patch.object(
            process_ancestry,
            "ps_lines",
            return_value=["  338     1"],
        ):
            self.assertEqual(process_table(), {338: (1, "")})

    def test_ps_failure_degrades_to_empty(self):
        with patch.object(process_ancestry, "ps_lines", return_value=[]):
            self.assertEqual(parent_map(), {})
            self.assertEqual(ancestor_pids(123), [])

    def test_anchor_dataclass_is_frozen(self):
        anchor = ProcessAnchor(pid=1, start_time="t", process_name="claude")
        with self.assertRaises(Exception):
            anchor.pid = 2  # type: ignore[misc]


if __name__ == "__main__":  # pragma: no cover - manual run
    unittest.main()
