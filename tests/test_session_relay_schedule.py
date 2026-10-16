from yoke_harness.session_relay_schedule import relay_run_lock

import pytest


def test_relay_run_lock_excludes_and_releases(tmp_path):
    with relay_run_lock(tmp_path) as first:
        assert first
        with relay_run_lock(tmp_path) as second:
            assert not second

    with relay_run_lock(tmp_path) as after_release:
        assert after_release


def test_relay_run_lock_does_not_hide_unexpected_lock_failure(tmp_path, monkeypatch):
    def fail(_descriptor):
        raise OSError("unexpected")

    monkeypatch.setattr(
        "yoke_harness.session_relay_schedule.platform_file_lock."
        "acquire_exclusive_nonblocking",
        fail,
    )

    with pytest.raises(OSError, match="unexpected"):
        with relay_run_lock(tmp_path):
            pass
