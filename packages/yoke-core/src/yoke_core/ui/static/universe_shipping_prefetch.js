// Start the authorized Shipping read without importing screen renderers.
import { parseUniverseRoute } from "./universe_navigation.js";
import { ROUTE_NAVIGATION_EVENT } from "./universe_path_navigation.js";
import { settledScopedCalls } from "./universe_view_support.js";

export function readShippingOverview(context) {
  return settledScopedCalls(context, [{
    functionId: "deployment_runs.list", payload: { relevance: "overview" },
  }]);
}

// Start the explicit Shipping entry's authorized read alongside bootstrap.
// Saved selection still controls its first paint. Consume once; navigation
// discards it, so a return or action always reads current release facts.
export function prefetchShippingOverview(context, windowNode, navigation) {
  const route = parseUniverseRoute(navigation.current(), navigation.basePath);
  if (route.view !== "shipping" || route.detail) return () => {};
  let initial = readShippingOverview(context);
  const discard = () => { initial = null; };
  context.takeShippingOverview = () => {
    const pending = initial;
    initial = null;
    return pending;
  };
  windowNode.addEventListener("popstate", discard);
  windowNode.addEventListener(ROUTE_NAVIGATION_EVENT, discard);
  return () => {
    discard();
    delete context.takeShippingOverview;
    windowNode.removeEventListener("popstate", discard);
    windowNode.removeEventListener(ROUTE_NAVIGATION_EVENT, discard);
  };
}
