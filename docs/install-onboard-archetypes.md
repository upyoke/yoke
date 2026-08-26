# External user archetypes — install and onboard

Research of the **current** public installer and onboard surfaces, confronted
with a sampled population of projects and users. This is not a plan to change
those surfaces; it is evidence of who they fit, where they break, and which
lifecycle claims have no declaration.

## Grounding

Transcripts quote live copy and commands from this tree. Invented screens are
forbidden. Sources:

| Surface | Authority |
|---|---|
| Public installer shim | `packaging/public-installer/install` |
| Installer Python helper | `packaging/public-installer/install.py` |
| Public install doc | `docs/public/install.md` |
| Destination / Account | `onboard_destination_rows.py`, `onboard_wizard_flow_destination.py` |
| PATH / Install step | `onboard_wizard_path.py` |
| GitHub copy | `onboard_github_copy.py`, `onboard_wizard_flow_github.py` |
| Project mode / identity | `onboard_wizard_steps.py`, `onboard_wizard_flow.py` |
| Publish / clone / branch | `onboard_wizard_project_screens.py`, `onboard_wizard_flow_publish.py` |
| Hosting | `onboard_wizard_hosting_steps.py` |
| Review | `onboard_wizard_review_steps.py` |
| Board art | `onboard_wizard_board_art.py`, `onboard_wizard_board_art_steps.py` |
| Modes | `docs/public/modes.md` |
| Harness onboard skill | `.agents/skills/yoke/onboard/` (SKILL + step files) |
| Idea deploy-default | `.agents/skills/yoke/idea/infer-and-create.md` |
| Usher routing | `.agents/skills/yoke/usher/deploy.md` |
| Windows git advice | `project_git_install_advice.py` |

## Dimensions (not an enumeration)

The population is a product of six independent axes. The full cross-product is
not useful; the sample below spans each value at least once.

| Axis | Values |
|---|---|
| User context | solo · small team · agency · pre-AI company · AI-native startup · large enterprise |
| Project stage | idea-only (no code) · vibe-coded mess · active product · mature / legacy |
| Hosting | none yet · DigitalOcean/VPS · AWS / managed cloud · PaaS · on-prem |
| OS | macOS · Windows · Linux |
| VCS / CI | no remote · GitHub with CI · GitHub without CI · other forge |
| Deploy shape | none · manual · CI/CD pipeline · app store |

## Sample (12 archetypes)

| ID | Persona | Context | Stage | Hosting | OS | VCS/CI | Deploy | File |
|---|---|---|---|---|---|---|---|---|
| A01 | Alex | solo | idea-only | none | macOS | no remote | none | [A01](install-onboard-archetypes/A01-solo-idea-macos.md) |
| A02 | Priya | solo | vibe-coded | DO/VPS | macOS | GitHub, no CI | manual | [A02](install-onboard-archetypes/A02-solo-vibe-vps-macos.md) |
| A03 | Marcus | AI-native startup | active | AWS | macOS (+Linux CI) | GitHub + CI | CI/CD | [A03](install-onboard-archetypes/A03-ainative-startup-aws.md) |
| A04 | Chen | small team | mature | PaaS | Windows | GitHub + CI | CI/CD | [A04](install-onboard-archetypes/A04-small-team-paas-windows.md) |
| A05 | Dana | agency | vibe / per-client | none yet | macOS | GitHub, no CI | manual | [A05](install-onboard-archetypes/A05-agency-github-manual.md) |
| A06 | Elena | pre-AI company | mature legacy | on-prem | Linux | GitLab + CI | CI/CD | [A06](install-onboard-archetypes/A06-preai-legacy-onprem.md) |
| A07 | Omar | large enterprise | mature | AWS | Linux | GitHub + CI | CI/CD | [A07](install-onboard-archetypes/A07-enterprise-aws-compliance.md) |
| A08 | Sam | solo | idea-only | none | Windows | no remote | none | [A08](install-onboard-archetypes/A08-solo-idea-windows.md) |
| A09 | Jules | small team | active | none (mobile) | macOS | GitHub + CI | app store | [A09](install-onboard-archetypes/A09-small-team-appstore.md) |
| A10 | Riley | AI-native | vibe-coded | none | Linux | GitHub, no CI | none | [A10](install-onboard-archetypes/A10-ainative-vibe-linux.md) |
| A11 | Pat | solo | mature | DO/VPS | Linux | Bitbucket | manual | [A11](install-onboard-archetypes/A11-solo-mature-other-forge.md) |
| A12 | Morgan | agency | idea-only | none (AWS later) | macOS | no remote | none | [A12](install-onboard-archetypes/A12-agency-greenfield.md) |

Coverage: every axis value appears. The sample is not a market-share ranking.

## Two surfaces, one journey

1. **Wire-up** — `curl -fsSL https://upyoke.com/install | sh` then the Textual
   wizard `yoke onboard` (PATH, Account, GitHub, Project, Hosting, Review).
2. **Execution-ready** — harness skill `/yoke onboard`: strategy docs,
   execution profile, Packs, hosting verification, environments/flows, gated
   first deploy, seeded work.

The installer hand-off after a successful interactive install is
(`print_path_guidance_after_onboard` in the shim): source the shell startup
file if PATH was new, "open Claude Code or Codex in your project folder", then
`/yoke onboard`. Cursor is a first-class executor in this repo and is not named
there.

## The suspected crux

Workflows and intake will **require** a deployment, environment, merge target,
or GitHub App binding that the archetype's project does not have — usually
because onboard **created a project default deploy flow** and `/yoke idea`
assigns it without asking.

Facts:

- Persistent flows name exactly one registered environment
  (`hosting-and-environments.md`). Merge-only flows exist (`target_tier` NULL)
  but onboard does not offer them.
- `/yoke idea` looks up `yoke project-structure deploy-defaults get` and, when
  non-empty, **always** uses that flow (`infer-and-create.md`).
- Usher Route A is empty/`-internal` flow → `yoke watch merge done-transition
  -- PREFIX-N --skip-deploy`. Route B is a real flow. Exit 7 if `--skip-deploy`
  is passed against a flow that requires a pipeline (`usher/deploy.md`).
- Hosting in the wizard is AWS-only (`HOSTING_CONNECT_SUBTITLE`: "AWS for now").
- The `vps-hosting` Pack provisions **AWS EC2**, not DigitalOcean.
- Native Windows install fails in the shim (`Darwin|Linux` only). Native
  Windows onboarding git advice: "not supported yet. Use WSL/Linux or macOS".

Where a requirement should be declared, what the refusal should say, and what a
project without that structure should get instead: see each archetype's crux
block and the [gap ledger](install-onboard-archetypes/gap-ledger.md).

## How to read an archetype file

Each file has: dimension vector · fit / break / gaps · literal install+wizard
transcript · literal `/yoke onboard` skill transcript · crux (declare / refuse /
instead) · ledger IDs. Follow-up items are indexed in the
[gap ledger](install-onboard-archetypes/gap-ledger.md) (YOK-2464–YOK-2474).
