// Shared DOM primitives and workbench chrome for the mounted universe app.

import { appendSlot } from "./mount-options.js";
import {
  buildUniverseRoute,
  NAV,
} from "./universe_navigation.js";
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
  chip.appendChild(el(documentNode, "span", "actor-name", name));
  if (actor.kind === "system") {
    chip.appendChild(el(
      documentNode, "span", "actor-kind",
      actor.systemComponent || "system",
    ));
  }
  return chip;
}

export function createPageHead(documentNode, entry) {
  const head = el(documentNode, "div", "page-head");
  const heading = el(documentNode, "div", "h");
  heading.appendChild(el(documentNode, "h1", "title", entry.label));
  if (entry.summary) {
    heading.appendChild(el(documentNode, "p", "subtitle", entry.summary));
  }
  head.appendChild(heading);
  if (entry.pageAction) {
    const action = el(
      documentNode,
      "a",
      "item-button primary page-head-action",
      entry.pageAction.label,
    );
    action.href = buildUniverseRoute(entry.pageAction.view, null);
    head.appendChild(action);
  }
  return head;
}

export function createBreadcrumb(documentNode, entry, project, detail) {
  const bar = el(documentNode, "div", "breadcrumb");
  const back = el(documentNode, "a", "breadcrumb-parent", entry.label);
  back.href = buildUniverseRoute(entry.id, project);
  bar.appendChild(back);
  bar.appendChild(el(documentNode, "span", "breadcrumb-sep", "/"));
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
  const orgContext = hostFillsTopbarStart
    ? null
    : el(documentNode, "span", "org-context", "…");
  const contextSide = el(
    documentNode, "div", "context-side yoke-header-context",
  );
  if (options.currentActor) {
    contextSide.appendChild(createActorChip(documentNode, options.currentActor));
  }
  if (orgContext) contextSide.appendChild(orgContext);
  const header = el(documentNode, "header", "topbar yoke-app-header");
  header.appendChild(brand);
  appendSlot(header, resolvedSlots.topbarStart, mountedSlotNodes);
  header.appendChild(contextSide);
  appendSlot(header, resolvedSlots.topbarEnd, mountedSlotNodes);

  const navEl = el(documentNode, "nav", "sidenav");
  const main = el(documentNode, "main", "content");
  const shell = el(documentNode, "div", "shell");
  appendSlot(navEl, resolvedSlots.navigationStart, mountedSlotNodes);
  shell.appendChild(navEl);
  appendSlot(shell, resolvedSlots.contentBefore, mountedSlotNodes);
  shell.appendChild(main);
  appendSlot(shell, resolvedSlots.contentAfter, mountedSlotNodes);

  const navLinks = new Map();
  for (const entry of NAV) {
    if (entry.hostFed && !resolvedSections[entry.id]) continue;
    const link = el(documentNode, "a", "nav-link");
    link.appendChild(el(documentNode, "span", "ico", entry.icon));
    link.appendChild(el(documentNode, "span", "txt", entry.label));
    navLinks.set(entry.id, link);
    navEl.appendChild(link);
  }
  appendSlot(navEl, resolvedSlots.navigationEnd, mountedSlotNodes);

  return { brand, header, main, navLinks, orgContext, shell };
}
