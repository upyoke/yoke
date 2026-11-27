# Harness manifest: global skill

The `global_skill` object of [`manifest.json`](manifest-schema.md) is rendered
from `yoke_contracts.harness_global_skill.HARNESS_GLOBAL_SKILLS`. It says where
the harness discovers the user-level `yoke-global` skill: the one Yoke skill
that is not a per-project copy. A session opened outside every Yoke project
uses it to check the machine, pick or add a project and name the folder where
a new session does the work. Its name differs from the project `yoke` skill,
so it never shadows one.

The skill lives once, in `~/.agents/skills/yoke-global`. `yoke setup` and
project install or refresh install it for every harness whose home folder
exists, and record each folder in the harness settings ledger so
`yoke uninstall` removes them.

| Key | Type | Description |
|-----|------|-------------|
| `source` | string | Canonical Python contract that owns the fact. |
| `name` | string | Skill name: `yoke-global`. |
| `harness_home` | string | Folder whose presence means the harness is installed. The installer never creates it. |
| `user_skills_dir` | string | User-level folder the harness reads skills from. |
| `placement` | string | `shared`: the harness reads the shared folder natively. `copy`: Yoke writes the same skill file into a real folder in `user_skills_dir`, never a link, because native Windows SSH sessions do not follow a user-created junction. |
| `shared_skill_dir` | string | The shared folder Codex and Cursor read. |
| `verified_on_surface` | string | Session surface where a live session listed the installed skill. Empty until observed. |
| `evidence` | string | What was observed, and when. |

A link an earlier release recorded is replaced by the copy without being
followed. A folder or link already at either path that Yoke did not record is
never overwritten: install reports `global_skill_path_not_owned` with the path and
the recovery step (move it aside, then run `yoke setup` again).
