from __future__ import annotations

from unittest.mock import patch

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
)
from yoke_core.domain.project_github_auth import ProjectGithubAuth
from yoke_core.tools import init_canonical_labels


def test_run_reads_colors_from_project_local_labels(tmp_path, monkeypatch) -> None:
    policy_dir = tmp_path / ".yoke"
    policy_dir.mkdir()
    (policy_dir / "labels").write_text(
        "label_color_status_idea=ABC123\n", encoding="utf-8"
    )
    monkeypatch.setenv("YOKE_TARGET_REPO_ROOT", str(tmp_path))
    auth = ProjectGithubAuth(
        project="buzz",
        repo="org/buzz",
        token="ghs_fake",
    )

    with patch.object(
        init_canonical_labels, "resolve_project_github_auth", return_value=auth
    ) as resolve_auth, patch.object(
        init_canonical_labels, "ensure_label",
    ) as ensure_label:
        assert init_canonical_labels.run("buzz") == 0

    resolve_auth.assert_called_once_with(
        "buzz",
        required_permissions=GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
    )
    idea_calls = [
        call for call in ensure_label.call_args_list if call.args[0] == "status:idea"
    ]
    assert idea_calls
    assert idea_calls[0].args[1] == "ABC123"
