"""Host-control fixture stdout for case-owned project cleanup."""


def fake_project_cleanup_stdout(argv):
    if argv[:2] == ["python3", "-c"]:
        return '{"retired_projects": [], "owner_marker_removed": true}'
    return ""
