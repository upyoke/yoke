"""Closed paths, URLs, and commands owned by permanent Machine QA fixtures."""

from pathlib import Path

from yoke_cli.config import path_doctor
from yoke_contracts.api_urls import DISTRIBUTION_PROD_URL, DISTRIBUTION_STAGE_URL


DISTRIBUTION_URL = DISTRIBUTION_STAGE_URL
HOSTED_PROD_API_URL = DISTRIBUTION_PROD_URL
HOSTED_STAGE_API_URL = DISTRIBUTION_STAGE_URL
SOURCE_DEV_ORIGIN = "https://github.com/upyoke/yoke.git"

YOKE_BIN = "{yoke_bin}"
ONBOARD = f"{YOKE_BIN} onboard"
POST_INSTALL_ONBOARD = f"{ONBOARD} --post-install"
MANAGED_BLOCK_MARKER = path_doctor.MANAGED_BEGIN.removeprefix("# >>> ").removesuffix(
    " >>>"
)
PATH_IDEMPOTENCE_STARTUP_FILES = tuple(
    str(path) for path in path_doctor.startup_files_for_shell("bash", Path("~"))
)

FAKE_TOKEN_PATH = "/tmp/yoke-fake-api.token"
STAGE_TOKEN_PATH = "/tmp/yoke-stage.token"
PROD_TOKEN_PATH = "/tmp/yoke-prod.token"
MISSING_TOKEN_PATH = "/tmp/yoke-missing.token"
EMPTY_TOKEN_PATH = "/tmp/yoke-empty.token"
INVALID_TOKEN_PATH = "/tmp/yoke-invalid.token"

SOURCE_NEW_PATH = "/tmp/yoke-project-source-new"
SOURCE_EXISTING_PATH = "/tmp/yoke-project-source-existing"
SOURCE_CONFLICT_PATH = "/tmp/yoke-project-source-conflict"
SOURCE_CLONE_MAIN_PATH = "/tmp/yoke-project-source-clone-main"
SOURCE_CLONE_MASTER_PATH = "/tmp/yoke-project-source-clone-master"
SOURCE_DEV_FRESH_PATH = "/tmp/yoke-project-source-dev-fresh"
SOURCE_DEV_EXISTING_PATH = "/tmp/yoke-project-source-dev-existing"
SOURCE_DEV_CONFLICT_PATH = "/tmp/yoke-project-source-dev-conflict"
SOURCE_DEV_DEFAULT_PATH = "/tmp/yoke-project-source-dev-default"
SOURCE_DEV_PUSH_PATH = "/tmp/yoke-project-source-dev-push"
META_CHECKOUT_PATH = "/tmp/yoke-project-meta-checkout"
META_CREATE_PATH = "/tmp/yoke-project-meta-create"
META_FAILURE_PATH = "/tmp/yoke-project-meta-board-data-fail"
PUBLISH_LOCAL_PATH = "/tmp/yoke-project-publish-local"

APPLY_CREATE_PATH = "/tmp/yoke-apply-create"
APPLY_CLONE_PATH = "/tmp/yoke-apply-clone"
APPLY_PROJECT_DENIED_PATH = "/tmp/yoke-apply-project-denied"
APPLY_CLONE_CONFLICT_PATH = "/tmp/yoke-apply-clone-conflict"
APPLY_BOARD_FAIL_PATH = "/tmp/yoke-apply-board-fail"
APPLY_RESUME_PATH = "/tmp/yoke-apply-resume"
APPLY_REPORT_AUDIT_PATH = "/tmp/yoke-apply-report-audit"
APPLY_CTRL_C_PATH = "/tmp/yoke-apply-ctrl-c"

SOURCE_SEEDS_PATH = "/tmp/yoke-project-source-seeds"
SOURCE_REMOTES_PATH = "/tmp/yoke-project-source-remotes"
SOURCE_DEV_REMOTES_PATH = "/tmp/yoke-project-source-dev-remotes"
SOURCE_MAIN_REMOTE_PATH = f"{SOURCE_REMOTES_PATH}/github.com/recipe/main-source.git"
SOURCE_MASTER_REMOTE_PATH = f"{SOURCE_REMOTES_PATH}/github.com/recipe/master-source.git"
SOURCE_DEV_REMOTE_PATH = f"{SOURCE_DEV_REMOTES_PATH}/github.com/upyoke/yoke.git"
SOURCE_DEV_SEED_PATH = f"{SOURCE_DEV_REMOTES_PATH}/source-dev-seed"
SOURCE_DEV_GIT_CONFIG_PATH = "/tmp/yoke-source-dev-post-apply.gitconfig"
SOURCE_DEV_REPORT_PATH = "/tmp/yoke-source-dev-post-apply.json"

STATE_PROJECT_ONE_PATH = "/tmp/yoke-state-project-one"
STATE_PROJECT_TWO_PATH = "/tmp/yoke-state-project-two"
STATE_PROJECT_MISSING_PATH = "/tmp/yoke-state-project-missing"

LONG_PROJECT_NAME = "yoke-term-long-project-name-" + ("a" * 32)
LONG_PROJECT_PATH = f"/tmp/{LONG_PROJECT_NAME}"

CAMPAIGN_WORKSPACE_PATHS = (
    SOURCE_NEW_PATH,
    SOURCE_EXISTING_PATH,
    SOURCE_CONFLICT_PATH,
    SOURCE_CLONE_MAIN_PATH,
    SOURCE_CLONE_MASTER_PATH,
    SOURCE_DEV_FRESH_PATH,
    SOURCE_DEV_EXISTING_PATH,
    SOURCE_DEV_CONFLICT_PATH,
    SOURCE_DEV_DEFAULT_PATH,
    SOURCE_DEV_PUSH_PATH,
    META_CHECKOUT_PATH,
    META_CREATE_PATH,
    META_FAILURE_PATH,
    PUBLISH_LOCAL_PATH,
    APPLY_CREATE_PATH,
    APPLY_CLONE_PATH,
    APPLY_PROJECT_DENIED_PATH,
    APPLY_CLONE_CONFLICT_PATH,
    APPLY_BOARD_FAIL_PATH,
    APPLY_RESUME_PATH,
    APPLY_REPORT_AUDIT_PATH,
    APPLY_CTRL_C_PATH,
    SOURCE_SEEDS_PATH,
    SOURCE_REMOTES_PATH,
    SOURCE_DEV_REMOTES_PATH,
)


__all__ = [
    "APPLY_BOARD_FAIL_PATH",
    "APPLY_CLONE_CONFLICT_PATH",
    "APPLY_CLONE_PATH",
    "APPLY_CREATE_PATH",
    "APPLY_CTRL_C_PATH",
    "APPLY_PROJECT_DENIED_PATH",
    "APPLY_REPORT_AUDIT_PATH",
    "APPLY_RESUME_PATH",
    "CAMPAIGN_WORKSPACE_PATHS",
    "DISTRIBUTION_URL",
    "EMPTY_TOKEN_PATH",
    "FAKE_TOKEN_PATH",
    "HOSTED_PROD_API_URL",
    "HOSTED_STAGE_API_URL",
    "INVALID_TOKEN_PATH",
    "LONG_PROJECT_NAME",
    "LONG_PROJECT_PATH",
    "MANAGED_BLOCK_MARKER",
    "META_CHECKOUT_PATH",
    "META_CREATE_PATH",
    "META_FAILURE_PATH",
    "MISSING_TOKEN_PATH",
    "ONBOARD",
    "POST_INSTALL_ONBOARD",
    "PATH_IDEMPOTENCE_STARTUP_FILES",
    "PROD_TOKEN_PATH",
    "PUBLISH_LOCAL_PATH",
    "SOURCE_CLONE_MAIN_PATH",
    "SOURCE_CLONE_MASTER_PATH",
    "SOURCE_CONFLICT_PATH",
    "SOURCE_DEV_CONFLICT_PATH",
    "SOURCE_DEV_DEFAULT_PATH",
    "SOURCE_DEV_EXISTING_PATH",
    "SOURCE_DEV_FRESH_PATH",
    "SOURCE_DEV_GIT_CONFIG_PATH",
    "SOURCE_DEV_ORIGIN",
    "SOURCE_DEV_PUSH_PATH",
    "SOURCE_DEV_REMOTE_PATH",
    "SOURCE_DEV_REMOTES_PATH",
    "SOURCE_DEV_REPORT_PATH",
    "SOURCE_DEV_SEED_PATH",
    "SOURCE_EXISTING_PATH",
    "SOURCE_MAIN_REMOTE_PATH",
    "SOURCE_MASTER_REMOTE_PATH",
    "SOURCE_NEW_PATH",
    "SOURCE_REMOTES_PATH",
    "SOURCE_SEEDS_PATH",
    "STAGE_TOKEN_PATH",
    "STATE_PROJECT_MISSING_PATH",
    "STATE_PROJECT_ONE_PATH",
    "STATE_PROJECT_TWO_PATH",
    "YOKE_BIN",
]
