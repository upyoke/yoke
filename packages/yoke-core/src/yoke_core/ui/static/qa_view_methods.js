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
          capability_samples: new Map(
            (row.required_capabilities || []).map((capability) => [
              capability.kind,
              {
                ...capability,
                states: new Set([capability.state]),
                contexts: [capability.context],
              },
            ]),
          ),
        });
        continue;
      }
      existing.used_by_plan_count += Number(row.used_by_plan_count || 0);
      for (const capability of row.required_capabilities || []) {
        const sample = existing.capability_samples.get(capability.kind);
        if (sample) {
          sample.states.add(capability.state);
          sample.contexts.push(capability.context);
        }
      }
    }
  }
  return [...methods.values()]
    .map((method) => {
      return {
        ...method,
        required_capabilities: [...method.capability_samples.values()]
          .map((capability) => {
            const state = capability.states.size === 1
              ? [...capability.states][0] : "mixed";
            return {
              ...capability,
              state,
              context: capability.contexts.length === 1
                ? capability.contexts[0] : { state },
            };
          }),
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
  foot.appendChild(el(documentNode, "span", null, "capabilities"));
  const capabilities = method.required_capabilities || [];
  if (!capabilities.length) {
    foot.appendChild(el(documentNode, "strong", "qa-capability-name", "none"));
  }
  for (const capability of capabilities) {
    foot.appendChild(el(
      documentNode, "strong", "qa-capability-name",
      capabilityLabel(capability.kind, capability.label),
    ));
    const state = capabilityStateNode(
      documentNode, capability.context, capability.state,
    );
    if (state) foot.appendChild(state);
  }
  card.appendChild(top);
  card.appendChild(description);
  card.appendChild(foot);
  return card;
}

function groupHeading(context, kinds, rows, scope) {
  const documentNode = context.document;
  const heading = el(documentNode, "p", "qa-group-label");
  if (!kinds.length) {
    heading.textContent = methodGroupLabel("");
    return heading;
  }
  heading.appendChild(el(documentNode, "span", null, "requires "));
  for (const [index, kind] of kinds.entries()) {
    if (index) heading.appendChild(el(documentNode, "span", null, " + "));
    const capability = el(
      documentNode, "a", "qa-capability-link", capabilityLabel(kind),
    );
    capability.href = capabilityRoute(context, scopeParam(scope), kind);
    heading.appendChild(capability);
  }
  if (kinds.includes("test-machine")) {
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
    const key = (method.required_capability_kinds || []).join("+");
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(method);
  }
  for (const [key, rows] of groups) {
    stack.appendChild(groupHeading(
      context, key ? key.split("+") : [], rows, scope,
    ));
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
