# Phase 4 — Buzz + Yoke checkout file inventory (B5, Wave 1)

Operator mandate: classify every file Yoke needs or wants present in an
external project repo — bundle-installed / project-authored / machine-level /
obsolete — including config surfaces the bundle does not ship. Sweep run
2026-06-12 against Buzz `main` (clean tree) and Yoke `main` (`d6868119c`);
suspicious claims re-verified directly.

## 1. Buzz classification (external-project shape)

| Group | Class | State |
| :--- | :--- | :--- |
| `.yoke/` contract files (README, lint-config, labels, board.json, board-art, test-inventory, template-deviations, runbooks×3) | bundle-installed | tracked, complete |
| `.yoke/project.config`, `.yoke/strategy/*.md` (4 placeholder docs) | bundle-installed | **present but GITIGNORED** — see §3 |
| `.yoke/board-art.example` | obsolete residue | **tracked** — the name was retired into the codified renderer (contract-seeding v0); delete + drop its gitignore negation |
| `.yoke/BOARD.md`, `.yoke/BOARD.md.ts` | generated-view | untracked (correct) |
| `.yoke/install-manifest.json` | bundle-installed install-state | untracked (correct — machine-written, self-heals) |
| `.claude/settings.json`, `.claude/agents/×7`, `.claude/rules/session.md` | bundle-installed | real files; hooks all `yoke hook evaluate` |
| `.codex/hooks.json`, `.codex/agents/×8` | bundle-installed | real files; env-pinned Codex spelling |
| `.agents/skills/yoke/**` (123 files) + `.claude/.codex` skill symlinks → in-repo tree | bundle-installed | correct; symlinks never point at a Yoke checkout |
| `AGENTS.md`, `CLAUDE.md`, `CODEX.md` | project-authored + Yoke marker blocks | correct joint ownership |
| `.github/workflows/buzz-*.yml`, `ci.yml` | project-authored | per §2.P ownership table |
| app/, docs/, build files | project-authored | untouched by installer |
| machine-level files in repo | — | **zero found** (correct) |

## 2. Yoke checkout (dev-source shape)

Project layer (.yoke/** contract + strategy views ×9) tracked and complete;
`.yoke/backups/` is **untracked** residue (verified — matches the I4A
disposition). `.claude/agents|rules|settings.json` and
`.codex/agents|hooks.json` are **symlinks into `runtime/harness/`** — the
dev-checkout shape that keeps rendered adapters live-editable; external
projects correctly get real files instead. `runtime/`, `templates/`, `docs/`
are product source, not install surface.

## 3. Finding: project gitignore policy breaks contract trackedness (GAP-6)

Buzz's root `.gitignore` carries a blanket `.yoke/*` ignore with a
hand-maintained negation allowlist authored before `project.config` and
`strategy/` existed. Verified: `git check-ignore` matches
`.yoke/project.config` and `.yoke/strategy/MISSION.md` against
`.gitignore:47`. Consequences: the I1A-PP deliveries sit silently ignored —
`project.config` cannot "ride the repo with teeth", strategy views cannot be
tracked rendered views, and every future contract file needs a manual
negation edit in each project. The allowlist also still blesses the retired
`board-art.example`.

**End-shape (GAP-6):** the install bundle ships `.yoke/.gitignore` as a
seeded contract file owning ignore policy for the `.yoke/` tree (ignore
only the generated/machine-state names: `BOARD.md`, `BOARD.md.ts`,
`BOARD.md.lock/`, `backups/`, `.github-retry.log`, `.merge-lock`,
`install-manifest.json`); everything else under `.yoke/` is tracked by
default. Projects then delete root-gitignore `.yoke` blocks entirely.
Buzz-side cleanup rides the Buzz proof: drop the root allowlist block, let
`.yoke/.gitignore` govern, `git add .yoke/project.config
.yoke/strategy/`, delete `.yoke/board-art.example` (+ its negation),
commit. Yoke's own root `.gitignore` gets the same treatment.

## 4. Finding: rendered agent bodies teach checkout-only fallbacks (GAP-7, deferred)

Buzz's installed Codex agent bodies (e.g. `.codex/agents/yoke-simulator.toml`)
retain `python3 -m runtime.api...` operator-debug fallback teaching — labeled
as such, and Buzz's AGENTS.md/CLAUDE.md marker blocks already instruct
treating those as stale install-layer teaching resolved via
`yoke <subcommand>`. On a no-checkout machine those fallbacks are dead
text, not leaks (no imports, no PYTHONPATH reach-around). **Disposition:
defer.** Stripping checkout-only fallback prose from external bundle renders
(a render-time conditional, like the existing `YOKE:HARNESS` blocks) is the
clean end-shape, but build it only if the Buzz smoke shows agents actually
reaching for the dead fallbacks — evidence-driven, recorded here so the
closeout report carries the decision.

## 5. No-checkout readiness assessment

Structurally ready: no symlinks into a Yoke checkout, no machine-level
files in the repo, hooks/skills/agents all teach `yoke <subcommand>`,
contract complete. The proof-blocking items are behavioral, not structural:
GAP-6 (trackedness), the Buzz residue cleanup, V3 (browser-QA bootstrap
proof), and whatever the live smoke surfaces (G3.P4.I4 burn-down).
