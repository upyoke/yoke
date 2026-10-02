"""What a Command-method QA case's shell is handed about its own subject.

Shared because the names are a contract with case authors: the runner that
exports them and the help that teaches them must agree, and those live on
opposite sides of the core/CLI boundary -- the packaged product CLI cannot
import engine code, so a name defined there would take the whole CLI down.

``BASE_URL`` names the target. The deployment pair names the run and member a
run-bound case answers for, so its command can address them instead of
hardcoding ids that name a run which has already happened; a case with no
such binding is handed neither, rather than an empty value that would read
as a run named ''.

Candidate-bound cases receive one JSON object naming their checkout root and
head_sha. Source wrappers use it to refuse switching to a lane; it does not
put candidate packages on the interpreter's import path.
"""

from __future__ import annotations


COMMAND_CASE_BASE_URL_ENV = "BASE_URL"
COMMAND_CASE_DEPLOYMENT_RUN_ENV = "DEPLOYMENT_RUN_ID"
COMMAND_CASE_DEPLOYMENT_MEMBER_ENV = "DEPLOYMENT_MEMBER_REF"
COMMAND_CASE_CANDIDATE_TREE_ENV = "YOKE_QA_CANDIDATE_TREE"


__all__ = [
    "COMMAND_CASE_BASE_URL_ENV",
    "COMMAND_CASE_CANDIDATE_TREE_ENV",
    "COMMAND_CASE_DEPLOYMENT_MEMBER_ENV",
    "COMMAND_CASE_DEPLOYMENT_RUN_ENV",
]
