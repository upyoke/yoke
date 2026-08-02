"""Unit tests for the session-registration corroboration guard.

Ambient resolution is injected in every test, so nothing reads the real
machine home, environment, or process tree.
"""

from __future__ import annotations

from yoke_cli.commands.session_begin_corroboration import (
    uncorroborated_reason,
)


_AMBIENT = "019fb914-2b50-7133-8065-e174775dc981"


class TestProceeds:
    def test_no_declared_id_defers_to_the_dispatcher(self):
        # The dispatcher stamps the ambient id, so there is nothing
        # uncorroborated for this guard to check.
        assert uncorroborated_reason(None, ambient_session_id=_AMBIENT) is None

    def test_blank_declared_id_is_treated_as_absent(self):
        assert uncorroborated_reason("   ", ambient_session_id=_AMBIENT) is None

    def test_declared_id_matching_ambient_proceeds(self):
        # The bootstrap helper passes the resolved id back explicitly.
        assert uncorroborated_reason(_AMBIENT, ambient_session_id=_AMBIENT) is None

    def test_surrounding_whitespace_does_not_break_the_match(self):
        assert uncorroborated_reason(
            f"  {_AMBIENT} ", ambient_session_id=_AMBIENT,
        ) is None


class TestRefuses:
    def test_minted_id_with_no_ambient_is_refused(self):
        # The observed shape: ambient resolution failed, so an id was
        # invented and declared instead of reporting the gap.
        reason = uncorroborated_reason(
            "f6300c3b-4a37-4b08-aa56-65d11c5a22e2", ambient_session_id="",
        )
        assert reason is not None
        assert "f6300c3b-4a37-4b08-aa56-65d11c5a22e2" in reason
        assert "no session id" in reason

    def test_id_diverging_from_ambient_is_refused(self):
        reason = uncorroborated_reason(
            "some-other-session", ambient_session_id=_AMBIENT,
        )
        assert reason is not None
        assert _AMBIENT in reason

    def test_refusal_names_the_operator_debug_override(self):
        reason = uncorroborated_reason("minted", ambient_session_id="")
        assert reason is not None
        assert "--session-id" in reason

    def test_refusal_does_not_teach_env_self_bootstrap(self):
        # The guard must not hand the caller a way to fabricate an ambient
        # id and walk straight back through itself.
        reason = uncorroborated_reason("minted", ambient_session_id="")
        assert reason is not None
        assert "export" not in reason.lower()
