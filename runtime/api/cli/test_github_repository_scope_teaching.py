"""Product App repository scope teaching across setup and status."""

import pytest

from yoke_cli.config import github_machine_report


@pytest.mark.parametrize("selection", ["selected", "all", None])
def test_repository_scope_recommendation_is_visible_in_setup_and_status(selection):
    from yoke_cli.config import onboard_wizard_github_presentation as presentation

    settings = "https://github.com/organizations/octo-org/settings/installations/123"
    report = {
        "ready": True,
        "access": {
            "installations": [
                {
                    "installation_id": 123,
                    "account_login": "octo-org",
                    "repository_selection": selection,
                    "html_url": settings,
                }
            ]
        },
    }
    for rendered in (
        github_machine_report.render_human(report),
        "\n".join(presentation.success_summary_lines(report)),
        "\n".join(presentation.success_notice_lines(report)),
    ):
        assert ('We recommend "All repositories"' in rendered) == (
            selection == "selected"
        )
        if selection == "selected":
            assert settings in rendered
            assert "every repository in this account" in rendered
            assert "new repositories" in rendered
    assert report["ready"] is True


def test_recommendation_names_each_selected_account_without_hiding_all_scope():
    report = {
        "access": {
            "installations": [
                {
                    "account_login": "octocat",
                    "repository_selection": "selected",
                    "html_url": "https://github.com/settings/installations/1",
                },
                {"account_login": "octo-org", "repository_selection": "all"},
                {
                    "account_login": "another-org",
                    "repository_selection": "selected",
                    "html_url": "https://github.com/organizations/another-org/settings/installations/3",
                },
            ]
        }
    }
    rendered = "\n".join(github_machine_report.repository_scope_recommendations(report))
    assert "octocat: We recommend" in rendered
    assert "another-org: We recommend" in rendered
    assert "octo-org: We recommend" not in rendered
    assert "https://github.com/settings/installations/1" in rendered
    assert (
        "https://github.com/organizations/another-org/settings/installations/3"
        in rendered
    )
