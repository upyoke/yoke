"""Mock gh script variants used by merge-worktree tests.

These string constants are sourced by test_merge_worktree_full.py's
_write_mock_gh helper. Each variant simulates a different gh-interaction
scenario the merge engine must handle.
"""
from __future__ import annotations

import textwrap


MOCK_GH_SCRIPT = textwrap.dedent("""\
    #!/usr/bin/env sh
    _log_file="$MOCK_GH_LOG"
    _cwd=$(pwd)
    echo "CWD=$_cwd ARGS=$*" >> "$_log_file"
    case "$1" in
      auth) exit 0 ;;
      pr)
        case "$2" in
          create) echo "https://github.com/test/repo/pull/1"; exit 0 ;;
          checks) exit 0 ;;
          merge)
            if [ -n "$MOCK_GH_ORIGIN" ]; then
              _merge_tmp="${MOCK_GH_ORIGIN}.merge-work"
              rm -rf "$_merge_tmp"
              git clone "$MOCK_GH_ORIGIN" "$_merge_tmp" >/dev/null 2>&1
              cd "$_merge_tmp"
              git config user.email "test@test.com"
              git config user.name "Test"
              _pr_branch=$(git branch -r 2>/dev/null | grep -v "HEAD" | grep -v "main" | head -1 | tr -d '[:space:]' | sed 's|origin/||')
              if [ -n "$_pr_branch" ]; then
                git merge "origin/${_pr_branch}" -m "Merge ${_pr_branch}" >/dev/null 2>&1
                git push origin main >/dev/null 2>&1
              fi
              cd /
              rm -rf "$_merge_tmp"
            fi
            exit 0
            ;;
          *) exit 0 ;;
        esac
        ;;
      *) exit 0 ;;
    esac
""")

# Variant mock that dirties a file during merge
MOCK_GH_DIRTY_SCRIPT = textwrap.dedent("""\
    #!/usr/bin/env sh
    _log_file="$MOCK_GH_LOG"
    _cwd=$(pwd)
    echo "CWD=$_cwd ARGS=$*" >> "$_log_file"
    case "$1" in
      auth) exit 0 ;;
      pr)
        case "$2" in
          create) echo "https://github.com/test/repo/pull/1"; exit 0 ;;
          checks) exit 0 ;;
          merge)
            if [ -n "$MOCK_GH_ORIGIN" ]; then
              _merge_tmp="${MOCK_GH_ORIGIN}.merge-work"
              rm -rf "$_merge_tmp"
              git clone "$MOCK_GH_ORIGIN" "$_merge_tmp" >/dev/null 2>&1
              cd "$_merge_tmp"
              git config user.email "test@test.com"
              git config user.name "Test"
              _pr_branch=$(git branch -r 2>/dev/null | grep -v "HEAD" | grep -v "main" | head -1 | tr -d '[:space:]' | sed 's|origin/||')
              if [ -n "$_pr_branch" ]; then
                git merge "origin/${_pr_branch}" -m "Merge ${_pr_branch}" >/dev/null 2>&1
                git push origin main >/dev/null 2>&1
              fi
              cd /
              rm -rf "$_merge_tmp"
            fi
            if [ -n "$MOCK_DIRTY_FILE" ]; then
              echo "modified during merge" > "$MOCK_DIRTY_FILE"
            fi
            exit 0
            ;;
          *) exit 0 ;;
        esac
        ;;
      *) exit 0 ;;
    esac
""")

MOCK_GH_PR_CREATE_HARD_FAIL = textwrap.dedent("""\
    #!/usr/bin/env sh
    _log_file="$MOCK_GH_LOG"
    _cwd=$(pwd)
    echo "CWD=$_cwd ARGS=$*" >> "$_log_file"
    case "$1" in
      auth) exit 0 ;;
      pr)
        case "$2" in
          create)
            echo "error: GraphQL error: branch not found" >&2
            exit 1
            ;;
          list) echo ""; exit 0 ;;
          checks) exit 0 ;;
          merge)
            echo "FATAL: pr merge should not be reachable in pr_create_hard_fail" >&2
            exit 99
            ;;
          *) exit 0 ;;
        esac
        ;;
      *) exit 0 ;;
    esac
""")

MOCK_GH_PR_CREATE_EMPTY_URL = textwrap.dedent("""\
    #!/usr/bin/env sh
    _log_file="$MOCK_GH_LOG"
    _cwd=$(pwd)
    echo "CWD=$_cwd ARGS=$*" >> "$_log_file"
    case "$1" in
      auth) exit 0 ;;
      pr)
        case "$2" in
          create)
            # exit 0 but with no URL on stdout — engine must hard-fail
            exit 0
            ;;
          list) echo ""; exit 0 ;;
          checks) exit 0 ;;
          merge)
            echo "FATAL: pr merge should not be reachable with empty URL" >&2
            exit 99
            ;;
          *) exit 0 ;;
        esac
        ;;
      *) exit 0 ;;
    esac
""")

MOCK_GH_PR_EXISTS_REUSE = textwrap.dedent("""\
    #!/usr/bin/env sh
    _log_file="$MOCK_GH_LOG"
    _cwd=$(pwd)
    echo "CWD=$_cwd ARGS=$*" >> "$_log_file"
    case "$1" in
      auth) exit 0 ;;
      pr)
        case "$2" in
          create)
            echo "a pull request for branch YOK-N into branch main already exists" >&2
            exit 1
            ;;
          list)
            echo '{"number":42,"url":"https://github.com/test/repo/pull/42"}'
            exit 0
            ;;
          checks) exit 0 ;;
          merge)
            if [ -n "$MOCK_GH_ORIGIN" ]; then
              _merge_tmp="${MOCK_GH_ORIGIN}.merge-work"
              rm -rf "$_merge_tmp"
              git clone "$MOCK_GH_ORIGIN" "$_merge_tmp" >/dev/null 2>&1
              cd "$_merge_tmp"
              git config user.email "test@test.com"
              git config user.name "Test"
              _pr_branch=$(git branch -r 2>/dev/null | grep -v "HEAD" | grep -v "main" | head -1 | tr -d '[:space:]' | sed 's|origin/||')
              if [ -n "$_pr_branch" ]; then
                git merge "origin/${_pr_branch}" -m "Merge ${_pr_branch}" >/dev/null 2>&1
                git push origin main >/dev/null 2>&1
              fi
              cd /
              rm -rf "$_merge_tmp"
            fi
            exit 0
            ;;
          *) exit 0 ;;
        esac
        ;;
      *) exit 0 ;;
    esac
""")

MOCK_GH_PR_EXISTS_UNRESOLVABLE = textwrap.dedent("""\
    #!/usr/bin/env sh
    _log_file="$MOCK_GH_LOG"
    _cwd=$(pwd)
    echo "CWD=$_cwd ARGS=$*" >> "$_log_file"
    case "$1" in
      auth) exit 0 ;;
      pr)
        case "$2" in
          create)
            echo "a pull request for branch already exists" >&2
            exit 1
            ;;
          list)
            echo ""
            exit 0
            ;;
          checks) exit 0 ;;
          merge)
            echo "FATAL: pr merge should not be reachable when PR unresolvable" >&2
            exit 99
            ;;
          *) exit 0 ;;
        esac
        ;;
      *) exit 0 ;;
    esac
""")

MOCK_GH_PR_MERGE_FAIL = textwrap.dedent("""\
    #!/usr/bin/env sh
    _log_file="$MOCK_GH_LOG"
    _cwd=$(pwd)
    echo "CWD=$_cwd ARGS=$*" >> "$_log_file"
    case "$1" in
      auth) exit 0 ;;
      pr)
        case "$2" in
          create) echo "https://github.com/test/repo/pull/1"; exit 0 ;;
          list) echo ""; exit 0 ;;
          checks) exit 0 ;;
          merge)
            echo "error: pull request is not mergeable: required status checks have not passed" >&2
            exit 1
            ;;
          *) exit 0 ;;
        esac
        ;;
      *) exit 0 ;;
    esac
""")

MOCK_GH_NO_CHECKS_REPORTED = textwrap.dedent("""\
    #!/usr/bin/env sh
    _log_file="$MOCK_GH_LOG"
    _cwd=$(pwd)
    echo "CWD=$_cwd ARGS=$*" >> "$_log_file"
    case "$1" in
      auth) exit 0 ;;
      pr)
        case "$2" in
          create) echo "https://github.com/test/repo/pull/1"; exit 0 ;;
          list) echo ""; exit 0 ;;
          checks)
            echo "no checks reported on the 'YOK-N' branch" >&2
            exit 1
            ;;
          merge)
            if [ -n "$MOCK_GH_ORIGIN" ]; then
              _merge_tmp="${MOCK_GH_ORIGIN}.merge-work"
              rm -rf "$_merge_tmp"
              git clone "$MOCK_GH_ORIGIN" "$_merge_tmp" >/dev/null 2>&1
              cd "$_merge_tmp"
              git config user.email "test@test.com"
              git config user.name "Test"
              _pr_branch=$(git branch -r 2>/dev/null | grep -v "HEAD" | grep -v "main" | head -1 | tr -d '[:space:]' | sed 's|origin/||')
              if [ -n "$_pr_branch" ]; then
                git merge "origin/${_pr_branch}" -m "Merge ${_pr_branch}" >/dev/null 2>&1
                git push origin main >/dev/null 2>&1
              fi
              cd /
              rm -rf "$_merge_tmp"
            fi
            exit 0
            ;;
          *) exit 0 ;;
        esac
        ;;
      *) exit 0 ;;
    esac
""")

# Target-moved race: during pr checks (which happens immediately before the
# engine's freshness re-check), a rogue second committer pushes a new commit
# to origin/main.  The engine's captured SHA is now stale, so the freshness
    # check must detect this and abort before the merge command runs.
MOCK_GH_TARGET_MOVED_DURING_CI = textwrap.dedent("""\
    #!/usr/bin/env sh
    _log_file="$MOCK_GH_LOG"
    _cwd=$(pwd)
    echo "CWD=$_cwd ARGS=$*" >> "$_log_file"
    case "$1" in
      auth) exit 0 ;;
      pr)
        case "$2" in
          create) echo "https://github.com/test/repo/pull/1"; exit 0 ;;
          list) echo ""; exit 0 ;;
          checks)
            # Mutate origin/main behind the engine's back.
            if [ -n "$MOCK_GH_ORIGIN" ] && [ ! -f "$MOCK_GH_LOG.race-fired" ]; then
              touch "$MOCK_GH_LOG.race-fired"
              _race_tmp="${MOCK_GH_ORIGIN}.race-work"
              rm -rf "$_race_tmp"
              git clone "$MOCK_GH_ORIGIN" "$_race_tmp" >/dev/null 2>&1
              cd "$_race_tmp"
              git config user.email "test@test.com"
              git config user.name "Test"
              git checkout main >/dev/null 2>&1
              echo "unrelated change" > race-file.txt
              git add race-file.txt >/dev/null 2>&1
              git commit -m "concurrent push during CI" >/dev/null 2>&1
              git push origin main >/dev/null 2>&1
              cd /
              rm -rf "$_race_tmp"
            fi
            exit 0
            ;;
          merge)
            echo "FATAL: pr merge should not run after target-moved abort" >&2
            exit 99
            ;;
          *) exit 0 ;;
        esac
        ;;
      *) exit 0 ;;
    esac
""")
