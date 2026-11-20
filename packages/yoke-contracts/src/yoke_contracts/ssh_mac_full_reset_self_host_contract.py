"""Self-host stack contract for the dedicated Test Machine reset.

The reset tears down the self-host bundle's Compose stack through the live
container daemon. These constants name the client, the stack selector, and
the closed receipt lines that report what the daemon could and could not see.
"""

from __future__ import annotations

from yoke_contracts.self_host_paths import default_bundle_dir


# Container runtime the self-host bundle drives. The reset resolves the client
# from these absolute locations rather than from a login PATH, because the
# program runs with a deliberately clean PATH and a runtime it cannot see is a
# runtime whose containers it would silently leave running.
DOCKER_DESKTOP_CLI = "~/.docker/bin/docker"
CONTAINER_RUNTIME_PROCESS_ANCHOR = "/Applications/Docker.app/Contents/MacOS/com.docker.backend"
CONTAINER_RUNTIME_PATHS = (
    DOCKER_DESKTOP_CLI,
    "/usr/local/bin/docker",
    "/opt/homebrew/bin/docker",
)
CONTAINER_RUNTIME_STOP_TIMEOUT_SECONDS = 30
# Colima names the daemon socket when the restored home has no Docker context.
CONTAINER_RUNTIME_STARTER_PATHS = (
    "/usr/local/bin/colima",
    "/opt/homebrew/bin/colima",
)
CONTAINER_RUNTIME_START_TIMEOUT_SECONDS = 180
# Compose labels every object it creates with the project name it derives from
# the bundle directory. Selecting by that label removes the server's own
# containers and volumes while leaving a user's identically imaged ones alone.
COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
SELF_HOST_COMPOSE_PROJECT = default_bundle_dir().name
RESET_SELF_HOST_CONTAINERS_PREFIX = "YOKE_RESET_SELF_HOST_CONTAINERS_REMOVED_"
RESET_SELF_HOST_VOLUMES_PREFIX = "YOKE_RESET_SELF_HOST_VOLUMES_REMOVED_"
RESET_SELF_HOST_IMAGES_PREFIX = "YOKE_RESET_SELF_HOST_IMAGES_REMOVED_"
# 1 when the daemon listed the stack, 0 when the host has no runtime client.
# Zero counts mean nothing was there only when this reads 1.
RESET_SELF_HOST_REACHABLE_PREFIX = "YOKE_RESET_SELF_HOST_STACK_REACHABLE_"
# Closed failure detail for a runtime client whose daemon cannot list the
# stack. An unlistable daemon looks exactly like an empty one, so the reset
# refuses instead of reporting a clean host it could not see. Kind plus the
# client path ride stdout; the recovery is rebuilt from the kind.
RESET_SELF_HOST_STATE_PREFIX = "YOKE_RESET_SELF_HOST_STATE_"
RESET_SELF_HOST_KIND_DOCKER_UNREACHABLE = "docker_unreachable"
RESET_SELF_HOST_KIND_RUNTIME_STOP_FAILED = "runtime_stop_failed"
RESET_SELF_HOST_KINDS = (
    RESET_SELF_HOST_KIND_DOCKER_UNREACHABLE,
    RESET_SELF_HOST_KIND_RUNTIME_STOP_FAILED,
)
#: The executables each kind may name, so a receipt naming anything else is
#: rejected as not produced by the program that owns this contract.
RESET_SELF_HOST_KIND_PATHS = {
    RESET_SELF_HOST_KIND_DOCKER_UNREACHABLE: CONTAINER_RUNTIME_PATHS,
    RESET_SELF_HOST_KIND_RUNTIME_STOP_FAILED: (DOCKER_DESKTOP_CLI, *CONTAINER_RUNTIME_STARTER_PATHS),
}
RESET_SELF_HOST_RECOVERY = {
    RESET_SELF_HOST_KIND_DOCKER_UNREACHABLE: (
        "The container runtime client {runtime} cannot list the self-host "
        "stack, even after the reset tried to start the runtime, so the reset "
        "cannot tell a clean host from leftovers it could not see. Start the "
        "runtime as the test account (`{start}`), confirm `docker ps` "
        "answers, and rerun the reset."
    ),
    RESET_SELF_HOST_KIND_RUNTIME_STOP_FAILED: (
        "The reset started the container runtime with {runtime} to list the "
        "self-host stack and could not stop it again. Run `{stop}` as "
        "the test account, then rerun the reset."
    ),
}


__all__ = [
    "COMPOSE_PROJECT_LABEL",
    "DOCKER_DESKTOP_CLI",
    "CONTAINER_RUNTIME_PATHS",
    "CONTAINER_RUNTIME_PROCESS_ANCHOR",
    "CONTAINER_RUNTIME_STARTER_PATHS",
    "CONTAINER_RUNTIME_START_TIMEOUT_SECONDS",
    "CONTAINER_RUNTIME_STOP_TIMEOUT_SECONDS",
    "RESET_SELF_HOST_CONTAINERS_PREFIX",
    "RESET_SELF_HOST_IMAGES_PREFIX",
    "RESET_SELF_HOST_KINDS",
    "RESET_SELF_HOST_KIND_DOCKER_UNREACHABLE",
    "RESET_SELF_HOST_KIND_PATHS",
    "RESET_SELF_HOST_KIND_RUNTIME_STOP_FAILED",
    "RESET_SELF_HOST_REACHABLE_PREFIX",
    "RESET_SELF_HOST_RECOVERY",
    "RESET_SELF_HOST_STATE_PREFIX",
    "RESET_SELF_HOST_VOLUMES_PREFIX",
    "SELF_HOST_COMPOSE_PROJECT",
]
