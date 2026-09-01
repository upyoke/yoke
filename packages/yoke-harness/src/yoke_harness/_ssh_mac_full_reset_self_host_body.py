"""Self-host stack teardown for the dedicated Test Mac reset program.

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
self_host_container_ids() {
  "$1" ps -aq --filter \
    "label=$compose_project_label=$self_host_compose_project" 2>/dev/null || true
}

self_host_volume_ids() {
  "$1" volume ls -q --filter \
    "label=$compose_project_label=$self_host_compose_project" 2>/dev/null || true
}

self_host_container_image_ids() {
  local runtime="$1" id
  while IFS= read -r id; do
    [[ -n "$id" ]] || continue
    "$runtime" inspect --format '{{.Image}}' -- "$id" 2>/dev/null || true
  done
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
  runtime=$(container_runtime_path) || return 0
  containers=$(self_host_container_ids "$runtime")
  images=$(
    print -r -- "$containers" |
      self_host_container_image_ids "$runtime" |
      /usr/bin/sort -u
  )
  self_host_containers_removed=$(
    print -r -- "$containers" | remove_ids "$runtime" rm --force
  )
  volumes=$(self_host_volume_ids "$runtime")
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
# golden restore cannot reach, and this is where it becomes visible.
self_host_stack_is_absent() {
  local runtime
  runtime=$(container_runtime_path) || return 0
  [[ -z "$(self_host_container_ids "$runtime")" ]] || return 1
  [[ -z "$(self_host_volume_ids "$runtime")" ]] || return 1
}
"""


__all__ = ["SELF_HOST_FUNCTIONS"]
