"""Stored work-claim target kinds and their table constraint."""

TARGET_KIND_ITEM = "item"
TARGET_KIND_EPIC_TASK = "epic_task"
TARGET_KIND_PROCESS = "process"
TARGET_KIND_STEERING = "steering"
TARGET_KIND_MIGRATION_SERIALIZATION = "migration_serialization"
TARGET_KIND_QA_ADMISSION = "qa_admission"
TARGET_KIND_ROUTE_QUALIFICATION = "route_qualification"
#: The per-project deploy lock deployment runs once required. Nothing takes
#: one now; the kind stays readable because rows of it remain — released
#: history, and holds taken before the retirement until their holder
#: releases them by id.
TARGET_KIND_DEPLOY_SERIALIZATION = "deploy_serialization"
RETIRED_TARGET_KINDS = (TARGET_KIND_DEPLOY_SERIALIZATION,)
ALL_TARGET_KINDS = (
    TARGET_KIND_ITEM,
    TARGET_KIND_EPIC_TASK,
    TARGET_KIND_PROCESS,
    TARGET_KIND_STEERING,
    TARGET_KIND_MIGRATION_SERIALIZATION,
    TARGET_KIND_QA_ADMISSION,
    TARGET_KIND_ROUTE_QUALIFICATION,
    *RETIRED_TARGET_KINDS,
)

TARGET_KIND_CHECK_SQL = "target_kind IN (%s)" % ", ".join(
    f"'{kind}'" for kind in ALL_TARGET_KINDS
)
