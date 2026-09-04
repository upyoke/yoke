// Shared DOM primitives and workbench chrome for the mounted universe app.

import { appendSlot } from "./mount-options.js";
import {
  buildUniverseRoute,
  NAV,
  NAV_GROUPS,
} from "./universe_navigation.js";
import { createShellControls } from "./universe_shell_controls.js";
import { section } from "./universe_views.js";

export function el(documentNode, tag, className, text) {
  const node = documentNode.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function callFunction(client, functionId, payload, target) {
  const request = { function: functionId, payload: payload || {} };
  // Preserve the local proxy envelope: omit target unless a view supplies
  // one, so global-target reads keep their server-side default.
  if (target) request.target = target;
  return client.call(request);
}

// Whoever the viewer is acting as. The engine models an actor as an id and a
// kind and nothing else — a human actor has no name there, because a name
// belongs to an account and accounts are the host's.
function createActorChip(documentNode, actor) {
  const chip = el(documentNode, "span", "actor-chip");
  const name = actor.label || `actor ${actor.id}`;
  chip.appendChild(el(
    documentNode,
    "span",
    "actor-avatar",
    actor.kind === "system" ? "⚙" : name.slice(0, 1),
  ));
  chip.appendChild(el(documentNode, "span", "actor-name", name));
  if (actor.id !== undefined && actor.id !== null) {
    chip.appendChild(el(
      documentNode, "span", "actor-kind", `actor ${actor.id}`,
    ));
  } else if (actor.kind === "system") {
    chip.appendChild(el(
      documentNode, "span", "actor-kind",
      actor.systemComponent || "system",
    ));
  }
  return chip;
}

function contextControl(documentNode, label, value, className) {
  const control = el(
    documentNode, "div", `header-context-control ${className}`,
  );
  control.appendChild(el(
    documentNode, "span", "header-context-label", label,
  ));
  const host = el(documentNode, "div", "header-context-value");
  if (value) host.appendChild(value);
  control.appendChild(host);
  control.valueHost = host;
  return control;
}

export function configurePageHead(
  documentNode,
  head,
  { title, summary = null, actions = [] },
) {
  head.replaceChildren();
  if (title || summary) {
    const heading = el(documentNode, "div", "h");
    if (title) heading.appendChild(el(documentNode, "h1", "title", title));
    if (summary) heading.appendChild(el(documentNode, "p", "subtitle", summary));
    head.appendChild(heading);
  }
  if (actions.length) {
    const actionHost = el(documentNode, "div", "head-actions");
    for (const action of actions) actionHost.appendChild(action);
    head.appendChild(actionHost);
  }
  head.hidden = !head.children.length;
}

export function createPageHead(documentNode, entry) {
  const head = el(documentNode, "div", "page-head");
  const actions = [];
  if (entry.pageAction) {
    const action = el(
      documentNode,
      "a",
      "item-button primary page-head-action",
      entry.pageAction.label,
    );
    action.href = buildUniverseRoute(entry.pageAction.view, null);
    actions.push(action);
  }
  configurePageHead(documentNode, head, {
    title: entry.label,
    summary: entry.summary,
    actions,
  });
  return head;
}

export function createBreadcrumb(
  documentNode,
  entry,
  project,
  detail,
  tab = null,
) {
  const bar = el(documentNode, "div", "breadcrumb");
  const back = el(documentNode, "a", "breadcrumb-parent", entry.label);
  back.href = buildUniverseRoute(entry.id, project);
  bar.appendChild(back);
  if (tab) {
    bar.appendChild(el(documentNode, "span", "breadcrumb-sep", "›"));
    const tabLink = el(
      documentNode,
      "a",
      "breadcrumb-parent breadcrumb-tab",
      tab.label,
    );
    tabLink.href = buildUniverseRoute(entry.id, project, tab.id);
    bar.appendChild(tabLink);
  }
  bar.appendChild(el(documentNode, "span", "breadcrumb-sep", "›"));
  bar.appendChild(el(documentNode, "span", "breadcrumb-here", String(detail)));
  return bar;
}

export function drillInProject(scope, projects) {
  if (Array.isArray(scope)) return scope[0];
  if (scope === "all") return projects[0] ? String(projects[0].id) : null;
  return scope;
}

export function emptyUniversePanel(documentNode) {
  const panel = section(documentNode, "Universe");
  panel.renderEnvelope(
    { status: 200, envelope: { success: true, result: {} } },
    (body) => {
      body.appendChild(el(
        documentNode, "p", "empty", "no projects yet",
      ));
    },
  );
  return panel;
}

export function createWorkbenchChrome({
  client,
  documentNode,
  mountedSlotNodes,
  options,
  resolvedSections,
  resolvedSlots,
  slots,
}) {
  const brand = el(documentNode, "div", "brand yoke-header-brand");
  brand.style.color = "var(--yoke-ink)";
  const hostFillsTopbarStart =
    slots.topbarStart !== undefined && slots.topbarStart !== null;
  const hostFillsTopbarEnd =
    slots.topbarEnd !== undefined && slots.topbarEnd !== null;
  const mode = options.capabilities?.data?.portability?.mode || "local";
  const actor = !hostFillsTopbarEnd && (options.currentActor || (
    !hostFillsTopbarStart && mode !== "hosted"
      ? {
          kind: "human",
          label: mode === "selfhost" ? "actor unavailable" : "local actor",
        }
      : null
  ));
  const orgContext = !hostFillsTopbarStart && mode === "hosted"
    ? el(documentNode, "span", "org-context", "…")
    : (!hostFillsTopbarStart
      ? el(documentNode, "span", "org-context", "local") : null);
  const contextSide = el(
    documentNode, "div", "context-side yoke-header-context",
  );
  const scopeHost = el(documentNode, "div", "header-scope-host");
  const scopeContext = contextControl(
    documentNode, "Projects", scopeHost, "header-project-context",
  );
  scopeContext.hidden = true;
  contextSide.appendChild(scopeContext);
  if (hostFillsTopbarStart) {
    appendSlot(contextSide, resolvedSlots.topbarStart, mountedSlotNodes);
  } else if (orgContext) contextSide.appendChild(contextControl(
    documentNode, "Universe", orgContext, "header-universe-context",
  ));
  if (hostFillsTopbarEnd) {
    appendSlot(contextSide, resolvedSlots.topbarEnd, mountedSlotNodes);
  }
  if (actor) contextSide.appendChild(contextControl(
    documentNode,
    "Actor",
    createActorChip(documentNode, actor),
    "header-actor-context",
  ));
  const controls = createShellControls({ documentNode, client, options });
  const spacer = el(documentNode, "span", "header-spacer");
  const header = el(documentNode, "header", "topbar yoke-app-header");
  const navigationToggle = el(
    documentNode, "button", "navigation-toggle", "",
  );
  navigationToggle.type = "button";
  navigationToggle.setAttribute("aria-label", "Open navigation");
  navigationToggle.setAttribute("aria-controls", "universe-navigation");
  navigationToggle.setAttribute("aria-expanded", "false");
  for (let index = 0; index < 3; index += 1) {
    navigationToggle.appendChild(el(documentNode, "span"));
  }
  header.appendChild(navigationToggle);
  header.appendChild(brand);
  header.appendChild(controls.search);
  header.appendChild(spacer);
  header.appendChild(contextSide);

  const navEl = el(documentNode, "nav", "sidenav");
  navEl.id = "universe-navigation";
  const navigationScrim = el(
    documentNode, "button", "navigation-scrim",
  );
  navigationScrim.type = "button";
  navigationScrim.hidden = true;
  navigationScrim.setAttribute("aria-label", "Close navigation");
  const main = el(documentNode, "main", "content");
  const body = el(documentNode, "div", "workbench-body");
  const shell = el(documentNode, "div", "shell");
  appendSlot(navEl, resolvedSlots.navigationStart, mountedSlotNodes);
  shell.appendChild(navEl);
  shell.appendChild(navigationScrim);
  appendSlot(body, resolvedSlots.contentBefore, mountedSlotNodes);
  body.appendChild(main);
  appendSlot(body, resolvedSlots.contentAfter, mountedSlotNodes);
  shell.appendChild(body);
  shell.appendChild(controls.footer);

  // Grouped, and the heading is drawn only when the group has a destination
  // left after host-fed filtering — a local universe has no Members or
  // Billing, and a heading over nothing is a heading that lies.
  const navLinks = new Map();
  for (const group of NAV_GROUPS) {
    const entries = NAV.filter((entry) => (
      entry.group === group.id
      && !(entry.hostFed && !resolvedSections[entry.id])
    ));
    if (!entries.length) continue;
    if (group.label) {
      navEl.appendChild(el(documentNode, "div", "nav-group", group.label));
    }
    for (const entry of entries) {
      const link = el(documentNode, "a", "nav-link");
      link.appendChild(el(documentNode, "span", "ico", entry.icon));
      link.appendChild(el(documentNode, "span", "txt", entry.label));
      navLinks.set(entry.id, link);
      navEl.appendChild(link);
    }
  }
  appendSlot(navEl, resolvedSlots.navigationEnd, mountedSlotNodes);

  const setNavigationOpen = (open) => {
    const shown = Boolean(open);
    shell.classList.toggle("side-open", shown);
    documentNode.body?.classList.toggle("side-open", shown);
    navigationScrim.hidden = !shown;
    navigationToggle.setAttribute("aria-expanded", String(shown));
    navigationToggle.setAttribute(
      "aria-label", shown ? "Close navigation" : "Open navigation",
    );
  };
  navigationToggle.addEventListener("click", () => {
    setNavigationOpen(
      navigationToggle.getAttribute("aria-expanded") !== "true",
    );
  });
  navigationScrim.addEventListener("click", () => setNavigationOpen(false));
  for (const link of navLinks.values()) {
    link.addEventListener("click", () => setNavigationOpen(false));
  }
  const onEscape = (event) => {
    if (event.key === "Escape") setNavigationOpen(false);
  };
  documentNode.defaultView.addEventListener("keydown", onEscape);

  return {
    brand,
    disposeChrome() {
      controls.dispose();
      documentNode.defaultView.removeEventListener("keydown", onEscape);
      documentNode.body?.classList.remove("side-open");
    },
    header,
    main,
    navLinks,
    orgContext,
    scopeHost,
    setScopeVisible(visible) {
      scopeContext.hidden = !visible;
      if (!visible) scopeHost.replaceChildren();
    },
    shell,
  };
}
