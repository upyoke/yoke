fail() { echo "$*" >&2; exit 1; }
# apt_get ARGS... — a dead or hung package mirror must fail this script in
# minutes with a named reason instead of stalling a box restore: apt retries
# and times out each fetch, and every call is bounded. A healthy call takes
# well under a minute.
APT_TIMEOUT_SECONDS=600
apt_get() {
  _apt_status=0
  DEBIAN_FRONTEND=noninteractive timeout --kill-after=10 "$APT_TIMEOUT_SECONDS" \
    apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 \
    -o Acquire::https::Timeout=30 -o DPkg::Lock::Timeout=60 "$@" || _apt_status=$?
  if [ "$_apt_status" -eq 124 ] || [ "$_apt_status" -eq 137 ]; then
    fail "apt_mirror_timeout: apt-get $1 did not finish within ${APT_TIMEOUT_SECONDS}s, so a package mirror is slow or unreachable; check this host's DNS and outbound network, then re-run"
  elif [ "$_apt_status" -ne 0 ]; then
    fail "apt_failed: apt-get $* exited $_apt_status; read the apt output above ('Temporary failure resolving' or 'Unable to locate package' means a mirror is unreachable), fix it, then re-run"
  fi
}
fetch() {
  _fetch_url=$1
  shift
  timeout --kill-after=10 180 curl --fail --show-error --location \
    --connect-timeout 10 --retry 3 --retry-delay 2 --retry-max-time 150 \
    --max-time 30 "$_fetch_url" "$@" \
    || fail "fetch_failed: could not fetch $_fetch_url within 180s; check DNS and outbound network, then re-run"
}
