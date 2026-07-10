"""Tests for atomic remote-file convergence over SSH stdin."""

from __future__ import annotations

import subprocess

import pytest

from runtime.api.domain.test_deploy_remote import FakeRunner, _env
from yoke_core.domain.deploy_remote import push_remote_file, remove_remote_file


class TestPushRemoteFile:
    def test_secret_payload_travels_via_stdin_only(self):
        runner = FakeRunner()
        push_remote_file(
            runner,
            _env(),
            content="SECRET=value\n",
            remote_path="/opt/yoke-core/.env",
            mode="600",
            sudo=False,
        )
        call = runner.calls[0]
        assert call["input_text"] == "SECRET=value\n"
        joined = " ".join(call["argv"])
        assert "SECRET" not in joined
        assert "python3 -c" in joined
        assert "os.replace" in joined
        assert joined.endswith(" /opt/yoke-core/.env 600")
        assert "sudo" not in joined

    def test_sudo_prefix_when_requested(self):
        runner = FakeRunner()
        push_remote_file(
            runner,
            _env(),
            content="server {}\n",
            remote_path="/etc/nginx/sites-available/yoke-core.conf",
            mode="644",
            sudo=True,
        )
        assert runner.calls[0]["argv"][-1].startswith("sudo python3 -c ")
        assert runner.calls[0]["argv"][-1].endswith(
            " /etc/nginx/sites-available/yoke-core.conf 644"
        )

    def test_quotes_remote_path_before_sending_secret_stdin(self):
        runner = FakeRunner()
        push_remote_file(
            runner,
            _env(),
            content="PRIVATE KEY\n",
            remote_path="/opt/yoke/$(cat >&2)/private key.pem",
            mode="600",
            sudo=False,
        )

        remote_command = runner.calls[0]["argv"][-1]
        assert remote_command.endswith(" '/opt/yoke/$(cat >&2)/private key.pem' 600")
        assert "os.replace" in remote_command
        assert runner.calls[0]["input_text"] == "PRIVATE KEY\n"

    def test_home_relative_path_expands_without_exposing_suffix(self):
        runner = FakeRunner()
        push_remote_file(
            runner,
            _env(),
            content="{}\n",
            remote_path="~/.docker/config.json",
            mode="600",
            sudo=False,
        )

        remote_command = runner.calls[0]["argv"][-1]
        assert remote_command.endswith(' "$HOME"/.docker/config.json 600')

    def test_home_relative_suffix_remains_shell_quoted(self):
        runner = FakeRunner()
        push_remote_file(
            runner,
            _env(),
            content="{}\n",
            remote_path="~/.docker/$(cat >&2)/config file",
            mode="600",
            sudo=False,
        )

        remote_command = runner.calls[0]["argv"][-1]
        assert remote_command.endswith(
            " \"$HOME\"/'.docker/$(cat >&2)/config file' 600"
        )

    def test_writer_replaces_existing_file_without_partial_reader_view(
        self,
        tmp_path,
    ):
        target = tmp_path / "github app $(exit 71).pem"
        target.write_text("old-key\n", encoding="utf-8")
        runner = FakeRunner()
        push_remote_file(
            runner,
            _env(),
            content="new-key\n",
            remote_path=str(target),
            mode="600",
            sudo=False,
        )
        call = runner.calls[0]
        old_reader = target.open(encoding="utf-8")
        try:
            subprocess.run(
                ["sh", "-c", call["argv"][-1]],
                input=call["input_text"],
                text=True,
                check=True,
            )
            assert old_reader.read() == "old-key\n"
        finally:
            old_reader.close()
        assert target.read_text(encoding="utf-8") == "new-key\n"
        assert target.stat().st_mode & 0o777 == 0o600
        lock = tmp_path / f".{target.name}.lock"
        assert {path.name for path in tmp_path.iterdir()} == {
            target.name,
            lock.name,
        }
        assert lock.stat().st_mode & 0o777 == 0o600

    def test_writer_cleans_stranded_temp_without_following_symlink(
        self,
        tmp_path,
    ):
        target = tmp_path / "github-app-private-key.pem"
        orphan = tmp_path / ".github-app-private-key.pem.crashed.tmp"
        orphan.write_text("stranded-key\n", encoding="utf-8")
        orphan.chmod(0o600)
        sentinel = tmp_path / "sentinel"
        sentinel.write_text("keep\n", encoding="utf-8")
        symlink = tmp_path / ".github-app-private-key.pem.link.tmp"
        symlink.symlink_to(sentinel)
        unrelated = tmp_path / ".another-key.crashed.tmp"
        unrelated.write_text("unrelated\n", encoding="utf-8")
        runner = FakeRunner()

        push_remote_file(
            runner,
            _env(),
            content="current-key\n",
            remote_path=str(target),
            mode="600",
            sudo=False,
        )
        call = runner.calls[0]
        subprocess.run(
            ["sh", "-c", call["argv"][-1]],
            input=call["input_text"],
            text=True,
            check=True,
        )

        assert target.read_text(encoding="utf-8") == "current-key\n"
        assert not orphan.exists()
        assert symlink.is_symlink()
        assert sentinel.read_text(encoding="utf-8") == "keep\n"
        assert unrelated.read_text(encoding="utf-8") == "unrelated\n"

    def test_writer_lock_serializes_concurrent_replacements(self, tmp_path):
        target = tmp_path / "github-app-private-key.pem"
        runner = FakeRunner()
        push_remote_file(
            runner,
            _env(),
            content="unused",
            remote_path=str(target),
            mode="600",
            sudo=False,
        )
        command = runner.calls[0]["argv"][-1]
        processes = [
            subprocess.Popen(
                ["sh", "-c", command],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(2)
        ]
        payloads = ("first-key\n", "second-key\n")
        for process, payload in zip(processes, payloads):
            assert process.stdin is not None
            process.stdin.write(payload)
            process.stdin.close()
        for process in processes:
            assert process.wait(timeout=10) == 0, (
                process.stderr.read() if process.stderr is not None else ""
            )

        assert target.read_text(encoding="utf-8") in payloads
        assert not list(tmp_path.glob(f".{target.name}.*.tmp"))

    def test_remove_cleans_target_and_stranded_writer_temp(self, tmp_path):
        target = tmp_path / "github-app-private-key.pem"
        target.write_text("old-key\n", encoding="utf-8")
        orphan = tmp_path / ".github-app-private-key.pem.crashed.tmp"
        orphan.write_text("stranded-key\n", encoding="utf-8")
        orphan.chmod(0o600)
        runner = FakeRunner()

        remove_remote_file(
            runner,
            _env(),
            remote_path=str(target),
            sudo=False,
        )
        call = runner.calls[0]
        assert call["input_text"] is None
        assert " remove " in call["argv"][-1]
        subprocess.run(["sh", "-c", call["argv"][-1]], check=True)

        assert not target.exists()
        assert not orphan.exists()
        assert (tmp_path / f".{target.name}.lock").exists()

    def test_rejects_non_octal_mode_before_running_ssh(self):
        runner = FakeRunner()

        with pytest.raises(ValueError, match="octal"):
            push_remote_file(
                runner,
                _env(),
                content="PRIVATE KEY\n",
                remote_path="/opt/yoke/private-key.pem",
                mode="600; cat /dev/stdin",
            )

        assert runner.calls == []
