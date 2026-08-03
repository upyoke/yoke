import {
  callFunction,
  el,
  renderError,
  scopeBuckets,
  settledScopedCalls,
  statePill,
} from "./universe_view_support.js";
import { buildUniverseRoute } from "./universe_navigation.js";
import { relativeAge } from "./universe_time.js";

const LEGACY_METHOD_ICONS = {
  command: "⌥",
  "browser-check": "◎",
  "browser-inspection": "◉",
  "terminal-check": "⌨",
  "terminal-inspection": "⌘",
  "machine-state-check": "≡",
};

const LEGACY_CAPABILITY_LABELS = {
  "browser-control": "Browser control",
  "test-machine": "Test Mac",
};

const OUTCOME_EXPLANATIONS = {
  needs_review:
    "The recorded evidence does not yet have a conclusive verdict. Review " +
    "and Inbox state are shown only when their executor records exist.",
  queued: "This materialized case is queued and has not started yet.",
  waiting:
    "This case is waiting for its required capability or serial lease.",
  blocked_on_precondition:
    "The case's required host baseline could not be reached or verified, " +
    "so the case never ran.",
};

export function methodIcon(method) {
  if (method && typeof method === "object" && method.display_icon) {
    return method.display_icon;
  }
  const methodId = typeof method === "string" ? method : method?.id;
  return LEGACY_METHOD_ICONS[methodId] || "◉";
}

export function capabilityLabel(kind, definitionLabel = null) {
  return definitionLabel || (
    kind ? (LEGACY_CAPABILITY_LABELS[kind] || kind) : "none"
  );
}

export function sourceLabel(method) {
  if (method.source_kind === "built_in") return "built-in";
  if (method.source_kind === "pack") {
    return method.source_ref ? `Pack · ${method.source_ref}` : "Pack";
  }
  return "project local";
}

export function sourceNode(
  context,
  method,
  project = null,
  linkPack = true,
) {
  const documentNode = context.document;
  const source = el(
    documentNode,
    "span",
    `qa-source ${method.source_kind || "project_local"}`,
    sourceLabel(method),
  );
  if (method.source_kind === "pack" && !linkPack) {
    source.textContent = "Pack";
    return source;
  }
  if (
    method.source_kind !== "pack"
    || !method.source_ref
  ) return source;
  source.textContent = "Pack";
  const host = el(documentNode, "span", "qa-source-contract");
  host.appendChild(source);
  const link = el(
    documentNode,
    "a",
    "qa-source-link",
    `${method.source_ref} →`,
  );
  link.href = buildUniverseRoute(
    "packs", projectIdFor(context, project),
  );
  host.appendChild(link);
  return host;
}

export function executorContractNode(
  documentNode,
  executorId,
  executorGloss = "registered executor",
) {
  const node = el(documentNode, "span", "qa-executor-contract");
  node.appendChild(el(
    documentNode, "strong", "mono", executorId || "—",
  ));
  node.appendChild(el(
    documentNode,
    "small",
    null,
    `· ${executorGloss}`,
  ));
  return node;
}

export function capabilityStateNode(
  documentNode,
  capabilityContext,
  fallbackState = null,
  caseContext = false,
) {
  const state = capabilityContext?.state || fallbackState;
  const pill = statePill(
    documentNode,
    String(state || "").replaceAll("_", " "),
  );
  if (!pill || state !== "in_use") return pill;
  const itemRef = capabilityContext?.active_lease?.item_ref;
  if (caseContext) {
    pill.title = itemRef
      ? `The serial Test Mac lease is in use by ${itemRef} right now — ` +
        "this case queues; nothing about the plan is blocked."
      : "The serial Test Mac lease is held by another active execution " +
        "right now — this case queues; nothing about the plan is blocked.";
  } else {
    pill.title = itemRef
      ? `The serial Test Mac lease is in use by ${itemRef} right now. ` +
        "New machine cases queue without blocking their plans."
      : "The serial Test Mac lease is held by another active execution. " +
        "New machine cases queue without blocking their plans.";
  }
  return pill;
}

export function projectIdFor(context, project) {
  const row = context.projects().find(
    (candidate) => String(candidate.slug) === String(project)
      || String(candidate.id) === String(project),
  );
  return row ? String(row.id) : String(project || "");
}

export function qaRoute(context, tab, detail = null, project = null) {
  return buildUniverseRoute(
    "qa",
    projectIdFor(context, project),
    tab,
    detail,
  );
}

export function capabilityRoute(context, project, capabilityKind = null) {
  return buildUniverseRoute(
    "capabilities",
    projectIdFor(context, project),
    capabilityKind === "test-machine" ? "test-machine" : null,
  );
}

export function detailHead(documentNode, title, subtitle) {
  const head = el(documentNode, "div", "page-head qa-detail-page-head");
  const text = el(documentNode, "div", "h");
  text.appendChild(el(documentNode, "h1", "title", title));
  text.appendChild(el(documentNode, "p", "subtitle", subtitle));
  head.appendChild(text);
  return head;
}

export function keyValuePanel(documentNode, title, rows) {
  const panel = el(documentNode, "section", "panel qa-contract");
  const header = el(documentNode, "div", "panel-header");
  header.appendChild(el(documentNode, "h2", null, title));
  panel.appendChild(header);
  const list = el(documentNode, "dl", "qa-key-values");
  for (const [label, value] of rows) {
    list.appendChild(el(documentNode, "dt", null, label));
    const cell = el(documentNode, "dd");
    if (value && value.nodeType) cell.appendChild(value);
    else cell.textContent = String(value ?? "—");
    list.appendChild(cell);
  }
  panel.appendChild(list);
  return panel;
}

export function terminalContractRows(documentNode) {
  const completion = el(documentNode, "span");
  completion.appendChild(el(
    documentNode,
    "span",
    null,
    "declared per case — some checkpoints exist only on one exit path; " +
      "the executor distinguishes ",
  ));
  completion.appendChild(el(
    documentNode, "em", null, "checkpoint not reached",
  ));
  completion.appendChild(el(documentNode, "span", null, " from "));
  completion.appendChild(el(
    documentNode, "em", null, "checkpoint failed",
  ));
  completion.appendChild(el(
    documentNode,
    "span",
    null,
    ", and recording a shortcut run's screen is a fabricated verdict",
  ));
  return [
    [
      "Entry surface",
      "declared per case — the run starts at the surface that normally " +
        "launches the program under test; observability follows process " +
        "ancestry, so a checkpoint printed by the parent is invisible to " +
        "a run that starts deeper",
    ],
    ["Required completion", completion],
  ];
}

export function outcomeNode(
  documentNode,
  outcome,
  degradedReason = null,
  displayLabel = null,
  explanation = null,
) {
  const wrap = el(documentNode, "span", "qa-outcome");
  const outcomeId = String(outcome || "queued");
  const display = outcomeId.replaceAll("_", " ");
  const baseLabel = displayLabel || display;
  const label = degradedReason
    ? `${baseLabel} · capture degraded`
    : baseLabel;
  const pill = statePill(documentNode, display, label);
  if (pill) {
    pill.title = [
      explanation || OUTCOME_EXPLANATIONS[outcomeId] || "",
      degradedReason ? `Capture degraded: ${degradedReason}` : "",
    ].filter(Boolean).join(" ");
    wrap.appendChild(pill);
  }
  return wrap;
}

export function qaPanel(documentNode, title, count = null, hint = null) {
  const root = el(documentNode, "section", "panel");
  const header = el(documentNode, "div", "panel-header");
  const heading = el(documentNode, "h2", null, title);
  if (count !== null) {
    heading.appendChild(el(
      documentNode, "span", "panel-count", `· ${count}`,
    ));
  }
  header.appendChild(heading);
  if (hint) {
    header.appendChild(el(
      documentNode, "span", "qa-panel-context", hint,
    ));
  }
  root.appendChild(header);
  const body = el(documentNode, "div", "panel-body");
  root.appendChild(body);
  return { root, body };
}

export function tableWrap(documentNode, table) {
  const wrap = el(documentNode, "div", "qa-table-wrap");
  wrap.appendChild(table);
  return wrap;
}

export function relativeTimeNode(documentNode, value) {
  if (!value) return el(documentNode, "span", "muted", "—");
  const time = el(documentNode, "time", "qa-relative-time", relativeAge(value));
  time.dateTime = String(value);
  time.title = String(value);
  return time;
}

export function projectCalls(context, scope, functionId, payload = {}) {
  return scopeBuckets(scope, context.projects(), true).map((project) => ({
    functionId,
    payload: { ...payload, project },
  }));
}

export async function loadProjectCalls(context, scope, functionId, payload) {
  return settledScopedCalls(
    context,
    projectCalls(context, scope, functionId, payload),
  );
}

export async function oneProjectCall(
  context, functionId, project, payload = {},
) {
  try {
    return await callFunction(
      context.client, functionId, { ...payload, project },
    );
  } catch (error) {
    return {
      status: 0,
      envelope: { success: false, error: { message: String(error) } },
    };
  }
}

export function showFailure(documentNode, host, callResult) {
  const panel = el(documentNode, "section", "panel");
  const body = el(documentNode, "div", "panel-body");
  panel.appendChild(body);
  renderError(body, callResult);
  host.replaceChildren(panel);
}

export function methodGroupLabel(kind, state) {
  if (!kind) return "requires nothing — a checkout is enough";
  const base = `requires ${capabilityLabel(kind)}`;
  const suffix = state ? ` · ${String(state).replaceAll("_", " ")}` : "";
  return kind === "test-machine"
    ? `${base}${suffix} · serial lease`
    : `${base}${suffix}`;
}
