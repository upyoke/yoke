# Project context

```text
yoke project-structure get --project P --family context_routing --json
```

`entries` is a list. Read every `always` doc and each topic matching the
title, spec or AC by name or keyword:

- frontend: ui, page, component, css, theme, layout, login, form, button, modal, style, dashboard
- backend: api, server, endpoint, route, handler, middleware, database, query, migration
- testing: test, spec, e2e, assertion, fixture, mock
- deployment: deploy, ci, cd, workflow, infra, vps, nginx, docker

A failed read stops; never treat it as empty. Start
discovery from the paths these docs name.
