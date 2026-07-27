"""Closed values shared by Machine QA fixture validators."""

import re

from yoke_core.domain.machine_qa_fixture_constants import (
    APPLY_BOARD_FAIL_PATH,
    APPLY_CLONE_CONFLICT_PATH,
    APPLY_CREATE_PATH,
    APPLY_CTRL_C_PATH,
    APPLY_PROJECT_DENIED_PATH,
    APPLY_REPORT_AUDIT_PATH,
    APPLY_RESUME_PATH,
    CAMPAIGN_WORKSPACE_PATHS,
    HOSTED_PROD_API_URL,
    HOSTED_STAGE_API_URL,
    LONG_PROJECT_PATH,
    META_CHECKOUT_PATH,
    META_FAILURE_PATH,
    PUBLISH_LOCAL_PATH,
    SOURCE_CONFLICT_PATH,
    SOURCE_DEV_ORIGIN,
    SOURCE_DEV_SEED_PATH,
    SOURCE_EXISTING_PATH,
    SOURCE_MAIN_REMOTE_PATH,
    SOURCE_MASTER_REMOTE_PATH,
    STATE_PROJECT_MISSING_PATH,
    STATE_PROJECT_ONE_PATH,
    STATE_PROJECT_TWO_PATH,
)


EVIDENCE_NAME_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?")
PRODUCT_STATE_PATHS = (
    "~/" + ".local/share/uv/tools/yoke-cli",
    "~/" + ".local/bin/yoke",
)
STATE_PROJECTS = {
    STATE_PROJECT_ONE_PATH: 101,
    STATE_PROJECT_TWO_PATH: 102,
    STATE_PROJECT_MISSING_PATH: 404,
}


def _workspace_path(suffix: str) -> str:
    return next(path for path in CAMPAIGN_WORKSPACE_PATHS if path.endswith(suffix))


SOURCE_DEV_PATH_STATES = {
    _workspace_path("-source-dev-fresh"): "fresh",
    _workspace_path("-source-dev-existing"): "existing-yoke-checkout",
    _workspace_path("-source-dev-conflict"): "non-yoke-folder",
    _workspace_path("-source-dev-default"): "fresh",
    _workspace_path("-source-dev-push"): "fresh",
}
GENERIC_CHECKOUTS = {
    SOURCE_EXISTING_PATH: (
        "git-checkout",
        "main",
        "project-source",
    ),
    SOURCE_CONFLICT_PATH: (
        "nonempty-folder",
        "main",
        "occupied",
    ),
    META_CHECKOUT_PATH: (
        "git-checkout",
        "main",
        "project-meta",
    ),
    META_FAILURE_PATH: (
        "git-checkout",
        "main",
        "project-meta",
    ),
    PUBLISH_LOCAL_PATH: (
        "git-checkout",
        "main",
        "project-meta",
    ),
    APPLY_CREATE_PATH: (
        "git-checkout",
        "main",
        "project-meta",
    ),
    APPLY_PROJECT_DENIED_PATH: (
        "git-checkout",
        "main",
        "project-meta",
    ),
    APPLY_CLONE_CONFLICT_PATH: (
        "nonempty-folder",
        "main",
        "conflict",
    ),
    APPLY_BOARD_FAIL_PATH: (
        "git-checkout",
        "main",
        "project-meta",
    ),
    APPLY_RESUME_PATH: (
        "git-checkout",
        "main",
        "project-meta",
    ),
    APPLY_REPORT_AUDIT_PATH: (
        "git-checkout",
        "main",
        "project-meta",
    ),
    APPLY_CTRL_C_PATH: (
        "git-checkout",
        "main",
        "project-meta",
    ),
    LONG_PROJECT_PATH: (
        "git-checkout",
        "main",
        "project-meta",
    ),
}
REMOTE_FIXTURES = {
    "main-source": (
        "main",
        SOURCE_MAIN_REMOTE_PATH,
    ),
    "master-source": (
        "master",
        SOURCE_MASTER_REMOTE_PATH,
    ),
}
EXPECTED_CONNECTIONS = {
    "stage": {
        "transport": "https",
        "prod": False,
        "api_url": HOSTED_STAGE_API_URL,
        "token_path": "~/.yoke/secrets/stage.token",
        "token_state": "synthetic",
    },
    "prod": {
        "transport": "https",
        "prod": True,
        "api_url": HOSTED_PROD_API_URL,
        "token_path": "~/.yoke/secrets/prod.token",
        "token_state": "synthetic",
    },
}
COMPLETED_APPLY_STEPS = [
    "01-machine-config",
    "02-connection",
    "03-store-token-reference",
]
TERMINAL_SIZES = {(80, 24), (100, 32), (140, 40)}


__all__ = [
    "COMPLETED_APPLY_STEPS",
    "EVIDENCE_NAME_PATTERN",
    "EXPECTED_CONNECTIONS",
    "GENERIC_CHECKOUTS",
    "PRODUCT_STATE_PATHS",
    "REMOTE_FIXTURES",
    "SOURCE_DEV_ORIGIN",
    "SOURCE_DEV_PATH_STATES",
    "SOURCE_DEV_SEED_PATH",
    "STATE_PROJECTS",
    "TERMINAL_SIZES",
]
