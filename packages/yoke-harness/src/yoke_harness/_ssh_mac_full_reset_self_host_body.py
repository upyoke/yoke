"""Self-host stack teardown for the dedicated Test Machine reset program.

The golden restore replaces one home and nothing else. A self-hosting server
walk leaves state on both sides of that boundary: the bundle directory and the
container runtime's own data live in the home, but the running server does not
— it lives in the runtime's daemon, which keeps writing while the clear runs
and restarts its containers afterwards because the bundle asks it to.

So this phase does the two things the restore cannot. It removes the server's
containers, volumes, and images while the daemon can still name them, and it
stops the runtime application so the clear can replace the data directory
instead of racing a live writer. A host with no container runtime reaches the
same end state by having nothing to do, which is a clean pass, not a skip.
A stopped Colima is started so its stack can be listed, then stopped again
once verify has seen it. A runtime client whose daemon still cannot list the
stack is refused, because an unlistable daemon and an empty one look alike.
"""

SELF_HOST_FUNCTIONS = r"""
container_runtime_path() {
  local candidate
  for candidate in "${container_runtime_paths[@]}"; do
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

docker_unreachable() {
  failure_detail="$self_host_state_prefix$self_host_kind_docker_unreachable $1"
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

# One bounded runtime control call (colima start or stop). Its progress goes
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

start_stopped_container_runtime() {
  local starter
  starter=$(container_runtime_starter_path) || return 1
  run_container_runtime_control "$container_runtime_start_timeout" \
    "$starter" start || return 1
  self_host_runtime_started="$starter"
}

# Leaves the runtime as the reset found it: one this reset started is stopped
# again, one that was already running keeps running.
restore_container_runtime_state() {
  [[ -n "$self_host_runtime_started" ]] || return 0
  if run_container_runtime_control "$container_runtime_stop_timeout" \
    "$self_host_runtime_started" stop; then
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

# The application, not the daemon socket: quitting the runtime is what releases
# the multi-gigabyte disk image living inside the home the clear is about to
# replace. A backend that survives keeps writing into unlinked files and leaves
# the restore a destination it cannot reconcile.
stop_container_runtime_application() {
  local waited=0
  /usr/bin/pgrep -f "$container_runtime_anchor" >/dev/null 2>&1 || return 0
  self_host_runtime_stopped=1
  /usr/bin/pkill -f "$container_runtime_anchor" >/dev/null 2>&1 || true
  while (( waited < container_runtime_stop_timeout )); do
    /usr/bin/pgrep -f "$container_runtime_anchor" >/dev/null 2>&1 || return 0
    /bin/sleep 1
    waited=$((waited + 1))
  done
  /usr/bin/pkill -9 -f "$container_runtime_anchor" >/dev/null 2>&1 || true
  /bin/sleep 1
  ! /usr/bin/pgrep -f "$container_runtime_anchor" >/dev/null 2>&1
}

stop_self_host_stack() {
  local runtime containers volumes images
  self_host_containers_removed=0
  self_host_volumes_removed=0
  self_host_images_removed=0
  self_host_stack_reachable=0
  self_host_runtime_stopped=0
  self_host_runtime_started=""
  runtime=$(container_runtime_path) || return 0
  if ! containers=$(self_host_container_ids "$runtime"); then
    start_stopped_container_runtime || docker_unreachable "$runtime" || return 1
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
  self_host_stack_is_absent || return 1
  stop_container_runtime_application
}

# Absence is asserted against the daemon rather than against the filesystem: a
# runtime whose data root was moved outside the home is exactly the case the
# golden restore cannot reach, and this is where it becomes visible. The one
# daemon allowed to be silent is the application this reset quit itself, whose
# stack the stop phase already listed empty while it could still answer.
self_host_stack_is_absent() {
  local runtime containers volumes
  runtime=$(container_runtime_path) || return 0
  if containers=$(self_host_container_ids "$runtime") &&
    volumes=$(self_host_volume_ids "$runtime"); then
    [[ -z "$containers" && -z "$volumes" ]]
    return
  fi
  (( self_host_runtime_stopped )) && return 0
  docker_unreachable "$runtime"
}
"""


__all__ = ["SELF_HOST_FUNCTIONS"]
