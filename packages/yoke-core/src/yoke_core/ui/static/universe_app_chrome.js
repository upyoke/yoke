// Shared DOM primitives and workbench chrome for the mounted universe app.

import { appendSlot } from "./mount-options.js";
import { createActorMenu } from "./universe_actor_menu.js";
import { createOnboardingControl } from "./universe_onboarding_control.js";
import { armRevealPanelDismissal } from "./universe_reveal_panel.js";
import { buildSidebarNavigation } from "./universe_nav_sidebar.js";
import { attachNavigationDrawer } from "./universe_navigation_drawer.js";
import { buildUniverseRoute } from "./universe_navigation.js";
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
  { title, actions = [] },
) {
  head.replaceChildren();
  if (title) {
    const heading = el(documentNode, "div", "h");
    heading.appendChild(el(documentNode, "h1", "title", title));
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

// The remembered open/closed state for every collapsible nav group, read
// once per mount. A read that fails leaves every drawer at its closed
// default rather than blanking the sidebar over a preference.
function loadNavGroupPreferences(client, sidebar) {
  Promise.resolve()
    .then(() => callFunction(client, "ui_preferences.nav_group.list", {}))
    .then((callResult) => {
      if (!callResult?.envelope?.success) return;
      sidebar.applyRememberedGroups(callResult.envelope.result?.groups || {});
    })
    .catch(() => {});
}

export function createWorkbenchChrome({
  client,
  context,
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
  const actorMenu = actor
    ? createActorMenu(documentNode, client, actor) : null;
  if (actorMenu) contextSide.appendChild(contextControl(
    documentNode, "Actor", actorMenu.host, "header-actor-context",
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
  // Getting started lives in the navigation, and at narrow width beside the
  // control that opens it.
  const onboarding = createOnboardingControl(context);
  header.appendChild(navigationToggle);
  header.appendChild(onboarding.compactTrigger);
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
  navEl.appendChild(onboarding.host);
  appendSlot(navEl, resolvedSlots.navigationStart, mountedSlotNodes);
  shell.appendChild(navEl);
  shell.appendChild(navigationScrim);
  appendSlot(body, resolvedSlots.contentBefore, mountedSlotNodes);
  body.appendChild(main);
  appendSlot(body, resolvedSlots.contentAfter, mountedSlotNodes);
  shell.appendChild(body);
  shell.appendChild(controls.footer);
  shell.appendChild(onboarding.dialog);

  // Grouped, and the heading is drawn only when the group has a destination
  // left after host-fed filtering — a local universe has no Members or
  // Billing, and a heading over nothing is a heading that lies.
  const sidebar = buildSidebarNavigation({
    documentNode,
    navEl,
    resolvedSections,
    onGroupToggle(groupId, open) {
      // Persisted against the person, so the drawer an operator closed is
      // still closed on the next visit. A failure here loses the choice and
      // nothing else, so it does not disturb the render.
      Promise.resolve().then(() => callFunction(
        client, "ui_preferences.nav_group.set", { group_id: groupId, open },
      )).catch(() => {});
    },
  });
  const navLinks = sidebar.navLinks;
  loadNavGroupPreferences(client, sidebar);
  appendSlot(navEl, resolvedSlots.navigationEnd, mountedSlotNodes);

  const disposeNavigation = attachNavigationDrawer({
    documentNode, header, shell, navigation: navEl, toggle: navigationToggle,
    scrim: navigationScrim, body,
    footer: controls.footer, main, links: navLinks,
  });
  // Revealed panels — a claiming session, a status reason — float above
  // whichever view drew them, so the press-outside and Escape dismissal is
  // armed once for the mount rather than once per route render.
  const disposeRevealPanels = armRevealPanelDismissal(documentNode);

  return {
    brand,
    footer: controls.footer,
    disposeChrome() {
      disposeRevealPanels();
      actorMenu?.dispose();
      controls.dispose();
      disposeNavigation();
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
