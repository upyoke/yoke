"""Remove and verify the labeled self-host stack on the live Docker daemon.

The runtime data stays live across the home restore. Start a stopped daemon
to remove residue it retained, then restore its prior running state.
"""

SELF_HOST_FUNCTIONS = r"""
container_runtime_path() {
  local candidate
  for candidate in "${container_runtime_paths[@]}"; do
    [[ "$candidate" != "$docker_desktop_cli" ]] || candidate=$(docker_desktop_path)
    if [[ -x "$candidate" ]]; then
      print -r -- "$candidate"
      return 0
    fi
  done
  return 1
}

# Objects are selected by the Compose project label rather than by image name,
# because the bundle shares its database image with whatever else a user runs.
# A name match would delete their container; the label matches only the server's.
# Listing errors are never suppressed: a daemon that cannot answer returns the
# same empty list as one with nothing to remove.
self_host_container_ids() {
  "$1" ps -aq --filter \
    "label=$compose_project_label=$self_host_compose_project"
}

self_host_volume_ids() {
  "$1" volume ls -q --filter \
    "label=$compose_project_label=$self_host_compose_project"
}

self_host_container_image_ids() {
  local runtime="$1" id
  while IFS= read -r id; do
    [[ -n "$id" ]] || continue
    "$runtime" inspect --format '{{.Image}}' -- "$id" || return 1
  done
}

docker_desktop_path() {
  print -r -- "$home/${docker_desktop_cli#\~/}"
}

docker_desktop_is_running() {
  /usr/bin/pgrep -U "$reap_user" -f "$container_runtime_anchor" >/dev/null 2>&1
}

docker_unreachable() {
  local runtime="$1"
  [[ "$runtime" != "$(docker_desktop_path)" ]] || runtime="$docker_desktop_cli"
  failure_detail="$self_host_state_prefix$self_host_kind_docker_unreachable $runtime"
  return 1
}

container_runtime_starter_path() {
  local candidate
  for candidate in "${container_runtime_starter_paths[@]}"; do
    if [[ -x "$candidate" ]]; then
      print -r -- "$candidate"
      return 0
    fi
  done
  return 1
}

# One bounded runtime control call (colima status, start or stop). Its progress goes
# to stderr so stdout stays the closed receipt, and its own directory leads
# PATH because Colima drives the Lima binaries installed beside it.
run_container_runtime_control() {
  local timeout="$1" pid waited=0
  shift
  PATH="${1:h}:$PATH" "$@" >&2 &
  pid=$!
  while /bin/kill -0 "$pid" 2>/dev/null; do
    if (( waited >= timeout )); then
      /bin/kill -TERM "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
      return 1
    fi
    /bin/sleep 1
    waited=$((waited + 1))
  done
  wait "$pid"
}

connect_docker_desktop() {
  local runtime="$1"
  unset DOCKER_CONTEXT
  export DOCKER_HOST="unix://$home/.docker/run/docker.sock"
  if ! docker_desktop_is_running; then
    self_host_runtime_started="$docker_desktop_cli"
    run_container_runtime_control "$container_runtime_start_timeout" "$runtime" desktop start ||
      return 1
  fi
}

# Connects the client to Colima's own daemon. The client alone may target the
# default /var/run/docker.sock: the docker context Colima selects lives in the
# home a previous restore replaced. Colima names its socket, so the reset asks
# it, starting the runtime first only when it is stopped. Only a runtime this
# reset started is recorded, so a running one is never stopped afterwards.
connect_colima() {
  local starter runtime_status
  starter=$(container_runtime_starter_path) || return 1
  if ! run_container_runtime_control "$container_runtime_stop_timeout" \
    "$starter" status; then
    run_container_runtime_control "$container_runtime_start_timeout" \
      "$starter" start || return 1
    self_host_runtime_started="$starter"
  fi
  runtime_status=$(PATH="${starter:h}:$PATH" "$starter" status --json) ||
    return 1
  [[ "$runtime_status" =~ '"docker_socket":"(unix://[^"]+)"' ]] || return 1
  export DOCKER_HOST="${match[1]}"
}

# Leaves the runtime as the reset found it: one this reset started is stopped
# again, one that was already running keeps running.
restore_container_runtime_state() {
  [[ -n "$self_host_runtime_started" ]] || return 0
  local -a command
  if [[ "$self_host_runtime_started" == "$docker_desktop_cli" ]]; then
    if ! docker_desktop_is_running; then
      self_host_runtime_started=""
      return 0
    fi
    command=("$(docker_desktop_path)" desktop stop)
  else
    command=("$self_host_runtime_started" stop)
  fi
  if run_container_runtime_control "$container_runtime_stop_timeout" "${command[@]}"; then
    self_host_runtime_started=""
    return 0
  fi
  failure_detail="$self_host_state_prefix$self_host_kind_runtime_stop_failed"
  failure_detail+=" $self_host_runtime_started"
  return 1
}

remove_ids() {
  local removed=0 id
  while IFS= read -r id; do
    [[ -n "$id" ]] || continue
    if "$@" -- "$id" >/dev/null 2>&1; then
      removed=$((removed + 1))
    fi
  done
  print -r -- "$removed"
}

stop_self_host_stack() {
  local runtime containers volumes images
  self_host_containers_removed=0
  self_host_volumes_removed=0
  self_host_images_removed=0
  self_host_stack_reachable=0
  self_host_runtime_started=""
  runtime=$(container_runtime_path) || return 0
  if [[ "$runtime" == "$(docker_desktop_path)" ]]; then
    connect_docker_desktop "$runtime" || docker_unreachable "$runtime" || return 1
  fi
  if ! containers=$(self_host_container_ids "$runtime"); then
    [[ "$runtime" != "$(docker_desktop_path)" ]] && connect_colima &&
      containers=$(self_host_container_ids "$runtime") ||
      docker_unreachable "$runtime" || return 1
  fi
  images=$(
    print -r -- "$containers" | self_host_container_image_ids "$runtime"
  ) || docker_unreachable "$runtime" || return 1
  volumes=$(self_host_volume_ids "$runtime") ||
    docker_unreachable "$runtime" || return 1
  self_host_stack_reachable=1
  images=$(print -r -- "$images" | /usr/bin/sort -u)
  self_host_containers_removed=$(
    print -r -- "$containers" | remove_ids "$runtime" rm --force
  )
  self_host_volumes_removed=$(
    print -r -- "$volumes" | remove_ids "$runtime" volume rm --force
  )
  # Images are removed without force on purpose. A refusal here means another
  # container still uses the image, which makes it that workload's image and
  # not residue this reset owns, so the count reports what was actually freed.
  self_host_images_removed=$(
    print -r -- "$images" | remove_ids "$runtime" image rm
  )
  self_host_stack_is_absent
}

# Lists into the caller's containers and volumes.
self_host_stack_listed() {
  containers=$(self_host_container_ids "$1") &&
    volumes=$(self_host_volume_ids "$1")
}

# Check the daemon again after restore. Only Colima may need reconnection:
# the home that carried its Docker context has just been replaced.
self_host_stack_is_absent() {
  local runtime containers volumes
  runtime=$(container_runtime_path) || return 0
  if ! self_host_stack_listed "$runtime"; then
    [[ "$runtime" != "$(docker_desktop_path)" ]] &&
      connect_colima && self_host_stack_listed "$runtime" ||
      docker_unreachable "$runtime" || return 1
  fi
  [[ -z "$containers" && -z "$volumes" ]]
}
"""


__all__ = ["SELF_HOST_FUNCTIONS"]
