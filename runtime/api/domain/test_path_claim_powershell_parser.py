"""PowerShell write targets match the Bash parser's path-claim mutations."""

from __future__ import annotations

import pytest

from yoke_core.domain.path_claim_bash_guard import evaluate_payload
from yoke_core.domain.path_claim_bash_parser import SUPPRESSION_TOKEN, extract_mutations
from yoke_core.domain.path_claim_powershell_parser import extract_powershell_mutations


def _targets(command: str, cwd: str = "/repo") -> list[tuple[str, str]]:
    return [(m.verb, m.target_path) for m in extract_powershell_mutations(command, cwd)]


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("Set-Content -Path src/a.py -Value x", [("set-content", "src/a.py")]),
        ("sc src/a.py 'x'", [("set-content", "src/a.py")]),
        ("'x' | Out-File -FilePath:docs/b.md -Append", [("out-file", "docs/b.md")]),
        ("Remove-Item -Recurse -Force build, dist", [("remove-item", "build"), ("remove-item", "dist")]),
        ("rm old.txt", [("remove-item", "old.txt")]),
        ("Copy-Item a.txt -Destination lib/a.txt", [("copy-item", "lib/a.txt")]),
        ("mv a.txt b.txt", [("move-item", "b.txt"), ("move-item", "a.txt")]),
        ("New-Item -Path pkg -Name x.py -ItemType File", [("new-item", "pkg/x.py")]),
        ("mkdir newdir", [("new-item", "newdir")]),
        ("yoke status > out.log 2>$null", [("redirect", "out.log")]),
        ("git restore -- src/c.py", [("git restore", "src/c.py")]),
        ("Get-Content a.txt | Select-String x", []),
        ("Set-Content $env:TEMP\\scratch.txt x", []),
    ],
)
def test_powershell_mutations(command: str, expected: list[tuple[str, str]]) -> None:
    assert _targets(command) == expected


def test_bash_and_powershell_name_the_same_targets() -> None:
    bash = [(m.verb, m.target_path) for m in extract_mutations("rm src/a.py", "/repo")]
    assert [t for _, t in bash] == [t for _, t in _targets("Remove-Item src/a.py")]


@pytest.mark.parametrize(
    "command",
    [
        "Invoke-Expression 'rm x'",
        "iex $code",
        "powershell -Command \"Remove-Item x\"",
        "pwsh -c 'Set-Content a b'",
        "cmd /c del x",
        "bash -c 'rm x'",
        "echo \"unterminated",
    ],
)
def test_opaque_execution_fails_closed(command: str) -> None:
    assert [verb for verb, _ in _targets(command)] == ["ambiguous"]


def test_suppression_token_is_audited() -> None:
    assert _targets(f"Remove-Item x {SUPPRESSION_TOKEN}") == [("suppressed", SUPPRESSION_TOKEN)]


def test_set_location_after_a_command_moves_later_targets() -> None:
    assert _targets("git status; Set-Location sub; Remove-Item a.txt") == [
        ("remove-item", "/repo/sub/a.txt")
    ]


def test_guard_reads_the_powershell_parser_for_stamped_payloads(monkeypatch) -> None:
    seen: list[str] = []

    def _fake(name):
        def extract(command, cwd, home):
            seen.append(name)
            return []

        return extract

    monkeypatch.setattr(
        "yoke_core.domain.path_claim_bash_guard.extract_powershell_mutations", _fake("ps")
    )
    monkeypatch.setattr("yoke_core.domain.path_claim_bash_guard.extract_mutations", _fake("bash"))
    base = {"tool_name": "Bash", "cwd": "/repo", "tool_input": {"command": "rm a"}}
    evaluate_payload({**base, "yoke_shell_kind": "powershell"})
    evaluate_payload({**base, "yoke_shell_kind": "bash"})
    assert seen == ["ps", "bash"]
