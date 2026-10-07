"""Host-control fixture stdout for case-owned project cleanup."""

from yoke_contracts.qa_project_ownership import OWNER_CAPABILITY


def fake_project_cleanup_stdout(argv):
    if argv[:2] != ["python3", "-c"]:
        return ""
    if argv[-1] == OWNER_CAPABILITY:
        return '{"retired_projects": [], "owner_marker_removed": true}'
    if "inherited_owners" in argv[2]:
        return '{"previous_owner": null, "inherited_owners": []}'
    return '{"retired_projects": [], "owner_marker_removed": true}'
