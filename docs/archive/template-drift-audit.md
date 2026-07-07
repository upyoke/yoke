# Template Drift Audit: Buzz vs Yoke Templates

**Date:** 2026-03-12
**Auditor:** Engineer agent (YOK-760 task 001)
**Buzz source:** `/Users/dev/buzz` (current main)
**Template source:** `yoke/templates/webapp/`
**Rendered output:** `yoke/projects/buzz/workflows/`

## Classification Key

| Category | Definition | Fix Action |
|----------|-----------|------------|
| **A** | Parameterizable -- difference can be expressed as a `{{placeholder}}` | Update template + `python3 -m runtime.api.tools.render_project` |
| **B** | Approved non-generalizable -- legitimately project-specific, cannot be parameterized | Document in DEVIATIONS.md with operator approval |
| **C** | Pure drift -- diverged without justification | Update whichever side is wrong |

## Summary Table

| File | Buzz | Template | Rendered | Category | Fix Action |
|------|------|----------|----------|----------|------------|
| `buzz-deploy.yml` | `workflow_dispatch` only | `push: [main]` + `workflow_dispatch` | Has `push: [main]` | **C** | Buzz removed `push: [main]` trigger; rendered does not match Buzz |
| `buzz-deploy.yml` | `${{ secrets.BUZZ_SSH_USER }}` | `{{ssh_user}}` (hardcoded) | `openclaw` (hardcoded) | **A** | Template should render to `${{ secrets.X_SSH_USER }}` pattern |
| `buzz-deploy.yml` | "Add droplet to known hosts" | "Add host to known hosts" | "Add host to known hosts" | **C** | Buzz step name diverged; trivial |
| `buzz-deploy.yml` | No auto-generated header | Has header | Has header | **C** | Buzz repo has no header; rendered does |
| `buzz-hotfix.yml` | Exists | No template | Not in rendered output | **A** | Create `hotfix.yml` template |
| `buzz-smoke.yml` | `${{ secrets.BUZZ_SSH_USER }}` | `{{ssh_user}}` (hardcoded) | `openclaw` (hardcoded) | **A** | Same ssh_user issue as deploy |
| `buzz-smoke.yml` | "Add droplet to known hosts" | "Add host to known hosts" | "Add host to known hosts" | **C** | Buzz step name diverged |
| `buzz-ephemeral.yml` | rsync-based deploy | git-based deploy in template | git-based (rendered from template) | **C** | Major structural drift -- Buzz uses rsync, template uses git |
| `buzz-ephemeral.yml` | `openclaw` hardcoded | `{{ssh_user}}` | `openclaw` (rendered) | **A** | ssh_user should be secret ref |
| `buzz-ephemeral.yml` | Has "Checkout code" step | No checkout step | No checkout step | **C** | Buzz has checkout; template does not (template uses git on server) |
| `buzz-ephemeral.yml` | Has "Install rsync" step | No rsync step | No rsync step | **C** | Buzz uses rsync; template uses git |
| `buzz-ephemeral.yml` | Separate env config step | No env config step | No env config step | **C** | Buzz has .env copy/override; template relies on docker compose env |
| `buzz-ephemeral.yml` | `~/buzz-ephemeral/$SLUG` | `~/{{project_name}}-app` | `~/buzz-app` | **C** | Buzz uses dedicated ephemeral dirs; template reuses app dir |
| `buzz-ephemeral-teardown.yml` | Has `rm -rf` cleanup | No `rm -rf` | No `rm -rf` | **C** | Buzz cleans up ephemeral dirs; template only does docker compose down |
| `buzz-ephemeral-teardown.yml` | `openclaw` hardcoded | `{{ssh_user}}` | `openclaw` (rendered) | **A** | ssh_user should be secret ref |
| `buzz-ephemeral-teardown.yml` | `cd ~/buzz-ephemeral/$SLUG` fallback | Single docker compose down | Single docker compose down | **C** | Buzz teardown has dir-based + project-based fallback |
| `docker-compose.yml` | `network_mode: host` | Bridge networking | N/A (no scaffold render) | **B** | Multilogin requires host networking (see investigation below) |
| `docker-compose.yml` | `buzz-data` volume name | `app-data` volume name | N/A | **A** | Parameterize volume name: `{{project_name}}-data` |
| `docker-compose.yml` | No `ports:` (host mode) | `ports: "{{api_port}}:{{api_port}}"` | N/A | **B** | Consequence of host networking |
| `docker-compose.yml` | No `environment: API_URL` | `API_URL=http://api:{{api_port}}` | N/A | **B** | Host networking uses localhost; bridge needs service name |
| `docker-compose.yml` | No `networks:` section | `app-network: bridge` | N/A | **B** | Consequence of host networking |
| `docker-compose.yml` | Has `healthcheck` on web: NO | Has none on web: correct | N/A | **C** | Both lack web healthcheck -- consistent |
| `app/Dockerfile` | Playwright base image | `python:3.12-slim` | N/A | **B** | MLX/Multilogin requires Playwright + Node.js |
| `app/Dockerfile` | `socat curl jq procps nodejs` system deps | `curl` only | N/A | **B** | MLX scripts need socat, jq, procps, nodejs |
| `app/Dockerfile` | `pip install anthropic pyyaml` extras | Not present | N/A | **B** | Buzz pipeline requires anthropic + pyyaml |
| `app/Dockerfile` | Playwright python + chromium install | Not present | N/A | **B** | MLX requires Playwright browser |
| `app/Dockerfile` | Node.js Playwright package for CDP | Not present | N/A | **B** | MLX CDP helper requires Node.js playwright |
| `app/Dockerfile` | `mkdir -p /app/data/exports /app/data/errors` | `mkdir -p /app/data` | N/A | **A** | Parameterize data subdirs |
| `app/Dockerfile` | `BUZZ_DATA_DIR`, `BUZZ_HOST`, `BUZZ_PORT` | `APP_DATA_DIR`, `APP_HOST`, `APP_PORT` | N/A | **A** | Env var prefix: `{{PROJECT_NAME_UPPER}}` or keep generic `APP_` |
| `app/Dockerfile` | `EXPOSE 8000` | `EXPOSE {{api_port}}` | N/A | **A** | Already parameterized in template |
| `app/entrypoint.sh` | `#!/bin/bash` | `#!/usr/bin/env sh` | N/A | **C** | Buzz uses bash shebang unnecessarily |
| `app/entrypoint.sh` | Runs `seed.py` on startup | Does not run `seed.py` | N/A | **B** | Buzz seeds demo data on startup; generic template does not |
| `app/entrypoint.sh` | `BUZZ_HOST`, `BUZZ_PORT` env vars | `APP_HOST`, `APP_PORT` | N/A | **A** | Same env var prefix issue |
| `app/web/Dockerfile` | `EXPOSE 3000`, `PORT=3000` | `EXPOSE {{web_port}}`, `PORT={{web_port}}` | N/A | **A** | Already parameterized in template |
| `app/web/Dockerfile` | Otherwise identical | Identical | N/A | -- | No drift |
| `app/web/next.config.ts` | `http://localhost:8000` hardcoded | `process.env.API_URL \|\| "http://localhost:{{api_port}}"` | N/A | **C** | Buzz hardcodes API URL; template uses env var with fallback |

## Detailed Analysis

### 1. Workflow: `buzz-deploy.yml`

**Three-way comparison:** Buzz repo vs template (`deploy.yml`) vs rendered (`projects/buzz/workflows/buzz-deploy.yml`)

#### Buzz vs Template

| Line/Section | Buzz | Template | Category | Notes |
|---|---|---|---|---|
| Trigger | `workflow_dispatch` only | `push: [main]` + `workflow_dispatch` | **C** | Buzz intentionally removed auto-deploy on push to main. The template has both triggers. This is a deliberate operational decision that should be Category A (parameterizable trigger config) or kept as-is if Buzz wants manual-only deploys. |
| Step: known hosts | "Add droplet to known hosts" | "Add host to known hosts" | **C** | Cosmetic rename in Buzz |
| ssh_user | `${{ secrets.BUZZ_SSH_USER }}` | `{{ssh_user}}` | **A** | Buzz uses secret reference (better); template hardcodes via render. Fix: make template render to `${{ secrets.{{PROJECT_NAME_UPPER}}_SSH_USER }}` |
| Template comments | None | Template variable header comments | -- | Stripped during render; not relevant |

#### Rendered vs Buzz

| Aspect | Rendered | Buzz | Drift? |
|---|---|---|---|
| Trigger | `push: [main]` + `workflow_dispatch` | `workflow_dispatch` only | YES -- rendered has auto-deploy, Buzz does not |
| Step name | "Add host to known hosts" | "Add droplet to known hosts" | YES -- cosmetic |
| ssh_user | `openclaw` (hardcoded) | `${{ secrets.BUZZ_SSH_USER }}` | YES -- rendered is worse |
| Header | Auto-generated header present | No header | YES -- header not in Buzz repo |

#### Rendered vs Template (re-render check)

The rendered output in `projects/buzz/workflows/buzz-deploy.yml` is consistent with what `python3 -m runtime.api.tools.render_project` would produce from the current template with current config values. No stale render detected.

### 2. Workflow: `buzz-hotfix.yml`

**No template counterpart exists.** The hotfix workflow in Buzz is essentially identical to `buzz-deploy.yml` (same steps, same structure) but with `workflow_dispatch` only trigger and the name "Buzz Hotfix".

| Aspect | Category | Notes |
|---|---|---|
| Missing template | **A** | Create `hotfix.yml` template -- identical to `deploy.yml` minus `push: [main]` trigger |
| Not tracked in rendered output | **C** | `buzz-hotfix.yml` is not in `projects/buzz/workflows/` |

### 3. Workflow: `buzz-smoke.yml`

**Three-way comparison:** Buzz repo vs template (`smoke.yml`) vs rendered (`projects/buzz/workflows/buzz-smoke.yml`)

#### Buzz vs Template

| Line/Section | Buzz | Template | Category | Notes |
|---|---|---|---|---|
| Step: known hosts | "Add droplet to known hosts" | "Add host to known hosts" | **C** | Same cosmetic drift as deploy |
| ssh_user | `${{ secrets.BUZZ_SSH_USER }}` | `{{ssh_user}}` | **A** | Same ssh_user issue |

#### Rendered vs Buzz

| Aspect | Rendered | Buzz | Drift? |
|---|---|---|---|
| Step name | "Add host to known hosts" | "Add droplet to known hosts" | YES -- cosmetic |
| ssh_user | `openclaw` | `${{ secrets.BUZZ_SSH_USER }}` | YES -- rendered is worse |
| Header | Present | Absent | YES |

### 4. Workflow: `buzz-ephemeral.yml`

**Three-way comparison:** Buzz repo vs template (`ephemeral-deploy.yml`) vs rendered (`projects/buzz/workflows/buzz-ephemeral.yml`)

This workflow has the **most significant structural drift** of any file.

#### Buzz vs Template -- Major Structural Differences

| Aspect | Buzz | Template | Category |
|---|---|---|---|
| Deploy strategy | **rsync** (copies files from CI runner to VPS) | **git** (checks out code on VPS via git fetch/pull) | **C** |
| Checkout step | Has `actions/checkout@v4` + `Install rsync` | No checkout step | **C** |
| Ephemeral directory | `~/buzz-ephemeral/$SLUG/` (separate from prod) | `~/{{project_name}}-app` (same dir as prod!) | **C** |
| .env configuration | Copies prod `.env`, overrides ports + CORS | Passes ports as env vars to docker compose | **C** |
| SSH key file | `~/.ssh/id_ed25519` | `~/.ssh/id_ed25519` | -- |
| SSH user | `openclaw` hardcoded in ssh commands | `{{ssh_user}}` placeholder | **A** |
| Slugify step ordering | Before checkout (has `if:` on branch check) | Before port compute (different step order) | **C** |
| Checkout step | Uses `actions/checkout@v4` | No checkout (git ops on server) | **C** |
| Docker compose invocation | `PORT=$WEB_PORT docker compose -p "buzz-$SLUG" up -d --build` | `API_PORT=$API_PORT WEB_PORT=$WEB_PORT docker compose -f docker-compose.yml -p "{{project_name}}-$SLUG" up -d --build` | **C** |

**Assessment:** The Buzz ephemeral workflow is significantly better than the template. The Buzz version:
1. Uses rsync (consistent with prod deploy strategy) instead of git on the server
2. Creates isolated ephemeral directories instead of reusing the prod app dir
3. Properly copies and modifies `.env` for port isolation
4. Has a "Create ephemeral directory" step for clean setup

The template version would deploy ephemeral environments to the production directory, which is dangerous.

**Recommendation:** The template should be updated to match Buzz's rsync-based approach. This is Category C (template is wrong, Buzz is right).

#### Rendered vs Buzz

The rendered output follows the template (git-based approach), so it diverges massively from what Buzz actually uses. This is the clearest example of the render pipeline not matching production.

### 5. Workflow: `buzz-ephemeral-teardown.yml`

**Three-way comparison:** Buzz repo vs template (`ephemeral-teardown.yml`) vs rendered

#### Buzz vs Template

| Aspect | Buzz | Template | Category |
|---|---|---|---|
| Teardown strategy | `cd ~/buzz-ephemeral/$SLUG` with fallback + `rm -rf` cleanup | Single `docker compose -p ... down` | **C** |
| SSH user | `openclaw` hardcoded | `{{ssh_user}}` | **A** |
| Directory cleanup | `rm -rf ~/buzz-ephemeral/$SLUG` | No cleanup | **C** |
| Fallback pattern | Two attempts: dir-based then project-based | Single attempt | **C** |

**Assessment:** Buzz's teardown is more robust (matches the rsync-based ephemeral deploy). The template teardown is consistent with its own git-based ephemeral deploy but is inadequate for the rsync-based approach that Buzz actually uses.

### 6. Scaffold: `docker-compose.yml`

| Aspect | Buzz | Template | Category | Notes |
|---|---|---|---|---|
| `network_mode: host` | Both services | Not present (bridge) | **B** | See Multilogin investigation below |
| Volume name | `buzz-data` | `app-data` | **A** | Add `{{project_name}}-data` placeholder |
| Port mapping | None (host mode) | `"{{api_port}}:{{api_port}}"` | **B** | Consequence of networking mode |
| Web `environment` | None | `API_URL=http://api:{{api_port}}` | **B** | Host mode uses localhost implicitly |
| `networks` section | None | `app-network: bridge` | **B** | Consequence of networking mode |

### 7. Scaffold: `app/Dockerfile`

| Aspect | Buzz | Template | Category | Notes |
|---|---|---|---|---|
| Base image | `mcr.microsoft.com/playwright/python:v1.40.0-jammy` | `python:3.12-slim` | **B** | MLX/Multilogin requires Playwright base |
| System deps | `socat curl jq procps` + Node.js 20 | `curl` only | **B** | MLX scripts need these tools |
| Python extras | `anthropic pyyaml` | Not present | **B** | Buzz pipeline deps |
| Playwright install | Python package + chromium browser | Not present | **B** | MLX browser automation |
| Node.js Playwright | `npm install playwright` for CDP helper | Not present | **B** | MLX CDP helper |
| Data dirs | `/app/data/exports /app/data/errors` | `/app/data` | **A** | Could parameterize extra subdirs |
| Env var prefix | `BUZZ_` | `APP_` | **A** | Could parameterize as `{{PROJECT_NAME_UPPER}}_` |
| Port | `EXPOSE 8000` / `ENV BUZZ_PORT=8000` | `EXPOSE {{api_port}}` / `ENV APP_PORT={{api_port}}` | **A** | Already parameterized in template |

### 8. Scaffold: `app/entrypoint.sh`

| Aspect | Buzz | Template | Category | Notes |
|---|---|---|---|---|
| Shebang | `#!/bin/bash` | `#!/usr/bin/env sh` | **C** | Buzz uses bash unnecessarily; no bashisms in script |
| Comment header | "Buzz API entrypoint" | "{{project_display_name}} API entrypoint" | **A** | Already parameterized |
| Seed step | Runs `db/seed.py` on every startup | Does not run seed | **B** | Buzz seeds demo data; not all projects need this |
| Env var prefix | `BUZZ_HOST`, `BUZZ_PORT` | `APP_HOST`, `APP_PORT` | **A** | Same prefix issue |

### 9. Scaffold: `app/web/Dockerfile`

| Aspect | Buzz | Template | Category | Notes |
|---|---|---|---|---|
| `EXPOSE` / `PORT` | `3000` hardcoded | `{{web_port}}` parameterized | **A** | Already handled in template |
| All other lines | Identical | Identical | -- | No drift |

### 10. Scaffold: `app/web/next.config.ts`

| Aspect | Buzz | Template | Category | Notes |
|---|---|---|---|---|
| API URL | `"http://localhost:8000"` hardcoded | `process.env.API_URL \|\| "http://localhost:{{api_port}}"` | **C** | Template is better -- uses env var with fallback. Buzz should adopt the template pattern. |

## Multilogin / network_mode Investigation

**Question:** Is `network_mode: host` still required in Buzz's `docker-compose.yml`?

**Findings:**

1. **`multilogin.py` exists** at `app/utils/multilogin.py` -- a full wrapper for MLX bash scripts (acquire, release, CDP commands).

2. **Active code path:** `app/fetchers/sources/x_twitter.py` imports and uses `from utils.multilogin import acquire, navigate, release`. This is the X/Twitter source fetcher, which is a core Buzz feature.

3. **MLX scripts exist and are maintained:** `mlx-auth.sh`, `mlx-acquire.sh`, `mlx-cdp.sh`, `mlx-release.sh`, `mlx-cdp-helper.js` all exist in `app/scripts/`.

4. **The Dockerfile installs MLX dependencies:** Playwright base image, socat, jq, procps, Node.js, and Node.js Playwright package -- all for MLX.

5. **Why host networking is needed:** The Multilogin agent runs on the VPS host at `localhost:4422` (or similar port). The `mlx-acquire.sh` script connects to this agent to acquire browser profiles. With bridge networking, `localhost` inside the container would not reach the host's Multilogin agent. Docker's `host.docker.internal` could theoretically work, but the MLX scripts are written to use `localhost`.

**Conclusion:** `network_mode: host` IS still required. Multilogin/MLX is actively used for X/Twitter source fetching. Reclassifying to Category B.

**Revisit condition:** If Multilogin is removed from Buzz (or if MLX scripts are updated to use `host.docker.internal` or a dedicated Docker network), `network_mode: host` can be eliminated and Buzz can switch to bridge networking.

## Category Summary

### Category A (Parameterizable) -- 12 items

1. **ssh_user in all workflows** -- Template should render to `${{ secrets.{{PROJECT_NAME_UPPER}}_SSH_USER }}` instead of hardcoding
2. **hotfix.yml template missing** -- Create from generalized `buzz-hotfix.yml`
3. **Volume name** in docker-compose: `buzz-data` -> `{{project_name}}-data`
4. **Env var prefix** in Dockerfile: `BUZZ_*` -> `{{PROJECT_NAME_UPPER}}_*` or keep generic `APP_*`
5. **api_port** in Dockerfile: already parameterized in template (Buzz hardcodes `8000`)
6. **web_port** in web Dockerfile: already parameterized in template (Buzz hardcodes `3000`)
7. **Env var prefix** in entrypoint.sh: `BUZZ_HOST`/`BUZZ_PORT` -> `APP_HOST`/`APP_PORT`
8. **Data subdirectories** in Dockerfile: `/app/data/exports /app/data/errors` could be parameterized
9. **Deploy trigger** in deploy.yml: `push: [main]` presence could be parameterized (Buzz removed it)
10. **Comment header** in entrypoint.sh: already parameterized as `{{project_display_name}}`
11. **API URL** in web Dockerfile port/expose: already parameterized
12. **Ephemeral directory pattern** -- `~/{{project_name}}-ephemeral/$SLUG` could be parameterized

### Category B (Approved Non-Generalizable) -- 10 items

1. **`network_mode: host`** -- Required for Multilogin agent access
2. **No port mapping** in docker-compose -- Consequence of host networking
3. **No `environment: API_URL`** on web service -- Host networking uses localhost
4. **No `networks:` section** -- Consequence of host networking
5. **Playwright base image** in Dockerfile -- MLX requires Playwright + browsers
6. **Extra system deps** (socat, jq, procps, nodejs) -- MLX scripts require these
7. **Extra Python deps** (anthropic, pyyaml) -- Buzz pipeline requirements
8. **Playwright + Node.js Playwright installs** -- MLX browser automation
9. **`seed.py` in entrypoint** -- Buzz seeds demo data on startup
10. **MLX CDP helper Node.js package** -- Required for CDP protocol

### Category C (Pure Drift) -- 13 items

1. **Step name "droplet" vs "host"** in deploy.yml and smoke.yml -- Cosmetic drift
2. **Ephemeral workflow deploy strategy** -- Buzz uses rsync, template uses git (template is wrong)
3. **Ephemeral directory isolation** -- Buzz uses `~/buzz-ephemeral/$SLUG`, template reuses prod dir (template is wrong)
4. **Ephemeral .env configuration** -- Buzz copies/overrides prod .env, template has none
5. **Ephemeral teardown cleanup** -- Buzz does `rm -rf`, template does not
6. **Ephemeral teardown fallback** -- Buzz has dir-based + project-based fallback
7. **Shebang in entrypoint.sh** -- Buzz uses `#!/bin/bash`, should be `#!/usr/bin/env sh`
8. **next.config.ts API URL** -- Buzz hardcodes `localhost:8000`, template uses env var (template is better)
9. **Deploy trigger removed** -- Buzz has `workflow_dispatch` only, rendered has both
10. **Auto-generated headers** -- Rendered files have headers, Buzz repo files do not
11. **Hotfix not tracked** -- `buzz-hotfix.yml` not in `projects/buzz/workflows/`
12. **Checkout step in ephemeral** -- Buzz has it (for rsync), template does not
13. **Install rsync step** -- Buzz has it, template does not

## Recommendations for Downstream Tasks

### Task 002 (ssh_user fix)
- Remove `{{ssh_user}}` from template sed chain
- Replace all `{{ssh_user}}@` occurrences in templates with `${{ secrets.{{PROJECT_NAME_UPPER}}_SSH_USER }}@`
- The `${{ secrets.X }}` syntax must NOT be treated as a Yoke placeholder by the sed engine

### Task 003 (hotfix template)
- Create `hotfix.yml` from `deploy.yml`, removing `push: [main]` trigger
- Change name to `{{project_display_name}} Hotfix`
- Add rename mapping in `yoke/api/domain/project_renderer.py` (`render_workflows` `name_map`)

### Task 004 (scaffold rendering)
- Scaffold files needing placeholders: `docker-compose.yml`, `app/Dockerfile`, `app/entrypoint.sh.tmpl` (renders to `app/entrypoint.sh`, YOK-1370), `app/web/Dockerfile`, `app/web/next.config.ts`
- Output to `projects/{project}/scaffold/` mirroring template structure

### Task 005 (Category A/C fixes)
- Fix ephemeral deploy template to use rsync-based approach matching Buzz
- Fix ephemeral teardown template to include directory cleanup
- Update `next.config.ts` in Buzz to use env var pattern from template
- Consider whether `deploy.yml` trigger should be parameterizable

### Task 007 (documentation)
- Update DEVIATIONS.md with structured Category B entries including approval fields
- All 10 Category B items need operator sign-off
