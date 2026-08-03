import { el } from "./universe_view_support.js";
import {
  capabilityLabel,
  capabilityRoute,
  capabilityStateNode,
  loadProjectCalls,
  methodGroupLabel,
  methodIcon,
  qaRoute,
  showFailure,
  sourceNode,
} from "./qa_view_primitives.js";

export { renderQaMethodDetail } from "./qa_view_method_detail.js";

const LEGACY_METHOD_ORDER = [
  "command", "browser-check", "browser-inspection",
  "terminal-check", "terminal-inspection",
  "machine-state-check",
];

function methodOrder(method) {
  if (Number.isFinite(Number(method.display_order))) {
    return Number(method.display_order);
  }
  const index = LEGACY_METHOD_ORDER.indexOf(method.id);
  return index < 0 ? LEGACY_METHOD_ORDER.length : index;
}

function scopeParam(scope) {
  if (scope === "all" || scope === null) return null;
  return Array.isArray(scope) ? scope.join(",") : String(scope);
}

function combinedMethods(callResults) {
  const methods = new Map();
  for (const result of callResults) {
    for (const row of result.envelope.result?.rows || []) {
      const existing = methods.get(row.id);
      if (!existing) {
        methods.set(row.id, {
          ...row,
          used_by_plan_count: Number(row.used_by_plan_count || 0),
          capability_states: new Set([row.capability_state]),
          capability_contexts: [row.capability_context],
        });
        continue;
      }
      existing.used_by_plan_count += Number(row.used_by_plan_count || 0);
      existing.capability_states.add(row.capability_state);
      existing.capability_contexts.push(row.capability_context);
    }
  }
  return [...methods.values()]
    .map((method) => {
      const state = method.capability_states.size === 1
        ? [...method.capability_states][0] : "mixed";
      return {
        ...method,
        capability_state: state,
        capability_context: method.capability_contexts.length === 1
          ? method.capability_contexts[0]
          : { state },
      };
    })
    .sort((left, right) => (
      methodOrder(left) - methodOrder(right)
      || left.name.localeCompare(right.name)
    ));
}

function methodCard(context, method, scope) {
  const documentNode = context.document;
  const card = el(documentNode, "a", "qa-method-card");
  card.href = qaRoute(
    context, "methods", method.id, scopeParam(scope),
  );
  const top = el(documentNode, "span", "qa-method-top");
  top.appendChild(el(
    documentNode, "span", "qa-method-icon", methodIcon(method),
  ));
  const identity = el(documentNode, "span", "qa-method-identity");
  identity.appendChild(el(documentNode, "strong", null, method.name));
  const count = method.used_by_plan_count;
  identity.appendChild(el(
    documentNode, "span", "qa-method-usage",
    `used by ${count} ${count === 1 ? "plan" : "plans"}`,
  ));
  top.appendChild(identity);
  top.appendChild(sourceNode(
    context, method, scopeParam(scope), false,
  ));
  const description = el(
    documentNode, "span", "qa-method-description", method.description,
  );
  const foot = el(documentNode, "span", "qa-method-foot");
  foot.appendChild(el(documentNode, "span", null, "capability"));
  foot.appendChild(el(
    documentNode, "strong", "qa-capability-name",
    capabilityLabel(
      method.required_capability_kind,
      method.required_capability_label,
    ),
  ));
  const state = method.required_capability_kind
    ? capabilityStateNode(
      documentNode,
      method.capability_context,
      method.capability_state,
    )
    : null;
  if (state) foot.appendChild(state);
  card.appendChild(top);
  card.appendChild(description);
  card.appendChild(foot);
  return card;
}

function groupHeading(context, kind, rows, scope) {
  const documentNode = context.document;
  const heading = el(documentNode, "p", "qa-group-label");
  if (!kind) {
    heading.textContent = methodGroupLabel(kind);
    return heading;
  }
  heading.appendChild(el(documentNode, "span", null, "requires "));
  const capability = el(
    documentNode, "a", "qa-capability-link", capabilityLabel(kind),
  );
  capability.href = capabilityRoute(context, scopeParam(scope), kind);
  heading.appendChild(capability);
  const states = new Set(rows.map((row) => row.capability_state));
  const state = states.size === 1 ? [...states][0] : "mixed";
  heading.appendChild(el(documentNode, "span", null, " · "));
  const pill = capabilityStateNode(
    documentNode,
    rows.length === 1 ? rows[0].capability_context : { state },
    state,
  );
  if (pill) heading.appendChild(pill);
  if (kind === "test-machine") {
    heading.appendChild(el(
      documentNode, "span", null, " · serial lease",
    ));
  }
  return heading;
}

function renderRoster(context, host, methods, scope) {
  const documentNode = context.document;
  const stack = el(documentNode, "div", "qa-method-groups");
  if (!methods.length) {
    stack.appendChild(el(
      documentNode,
      "p",
      "empty qa-method-empty",
      "No QA methods are available in this project scope. Methods appear " +
        "when Yoke serves them and their required capability is configured.",
    ));
    host.replaceChildren(stack);
    return;
  }
  const groups = new Map();
  for (const method of methods) {
    const key = method.required_capability_kind || "";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(method);
  }
  for (const [kind, rows] of groups) {
    stack.appendChild(groupHeading(context, kind, rows, scope));
    const catalog = el(documentNode, "div", "qa-method-catalog");
    for (const method of rows) {
      catalog.appendChild(methodCard(context, method, scope));
    }
    stack.appendChild(catalog);
  }
  host.replaceChildren(stack);
}

export async function renderQaMethods(context, main, scope) {
  const documentNode = context.document;
  main.replaceChildren(el(
    documentNode, "p", "empty", "loading methods…",
  ));
  const { callResults, failed } = await loadProjectCalls(
    context, scope, "qa.method.list", {},
  );
  if (!context.isMounted()) return;
  if (failed) {
    showFailure(documentNode, main, failed);
    return;
  }
  renderRoster(context, main, combinedMethods(callResults), scope);
}
