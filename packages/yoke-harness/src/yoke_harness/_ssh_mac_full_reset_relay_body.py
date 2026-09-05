"""Relay-service teardown for the dedicated Test Mac reset program.

The golden restore replaces one home. launchd's registry is not inside it: a
loaded relay job survives the clear in launchd itself, and because the job
recreates its state directory as soon as it runs, the home comes back clean
and the verifier still finds Yoke state the service wrote seconds later. That
is not hypothetical — it is how one reset removed the home, reported the
restore complete, and failed its own absence check.

So this phase boots the service out before anything else is stopped or
cleared, and it reads launchd's own listing on both sides: the surface that
reveals a job with no running process is the surface that must stop naming it.
A host with no relay loaded has nothing to do, which is a clean pass rather
than a skip. A service still listed after its bootout stops the reset while
the home is intact, and names the label it could not unload.
"""

RELAY_SERVICE_FUNCTIONS = r"""
relay_service_list() {
  "$launchctl_path" list 2>/dev/null || true
}

# Only this account's Yoke relay. The canonical label and the per-environment
# instance labels come from the relay's own naming authority; every other
# launchd job on the host belongs to something this reset does not own.
relay_service_labels() {
  local pid service_status label
  relay_service_list |
  while read -r pid service_status label; do
    [[ -n "$label" ]] || continue
    case "$label" in
      "$relay_label"|"$relay_label_prefix"*) print -r -- "$label" ;;
    esac
  done
}

relay_services_are_absent() {
  [[ -z "$(relay_service_labels)" ]]
}

# One label for the receipt, reduced to the character set the closed output
# contract accepts rather than trusted as launchctl printed it.
relay_service_report_label() {
  local listed
  listed=(${(f)"$(relay_service_labels)"})
  print -r -- "${listed[1]//[^A-Za-z0-9._-]/_}"
}

unload_relay_service() {
  local label uid waited=0
  relay_unloaded_count=0
  uid=$(/usr/bin/id -u)
  for label in ${(f)"$(relay_service_labels)"}; do
    [[ -n "$label" ]] || continue
    "$launchctl_path" bootout "$relay_domain/$uid/$label" >/dev/null 2>&1 || true
    relay_unloaded_count=$((relay_unloaded_count + 1))
  done
  (( relay_unloaded_count > 0 )) || return 0
  while (( waited < relay_unload_timeout )); do
    if relay_services_are_absent; then
      return 0
    fi
    /bin/sleep 1
    waited=$((waited + 1))
  done
  failure_detail="$relay_service_prefix$relay_service_kind_unload_failed $(
    relay_service_report_label
  )"
  return 1
}
"""


__all__ = ["RELAY_SERVICE_FUNCTIONS"]
