// Workbench page views and usage analytics run from mount, through the installed Pack.
// They go to the mounted universe's own collector: the serving universe's
// `/api/events` on a Local or self-hosted workbench, and the collector the
// host names in `eventsEndpoint` when one host serves several universes.
import { configureEvents } from "./events.js";
import { startPageViews } from "./events_navigation.js";

export const SERVING_COLLECTOR = "/api/events";

export function collectorEndpoint(options = {}) {
  if (options.eventsEndpoint) return options.eventsEndpoint.replace(/\/+$/, "");
  return options.runtimeIdentity?.portabilityMode === "hosted" ? null : SERVING_COLLECTOR;
}

export function mountWorkbenchTelemetry(windowNode = window, options = {}) {
  const collector = collectorEndpoint(options);
  if (!collector) {
    console.warn("[events] collector_endpoint_unconfigured: a hosted mount passes eventsEndpoint "
      + "naming its own organization's collector; page views stay off until it does");
    return () => {};
  }
  let active = true;
  let stop = () => {};
  void (async () => {
    try {
      const response = await windowNode.fetch(`${collector}/config`, { credentials: "same-origin" });
      if (!response.ok) throw new Error(`collector_configuration_refused: HTTP ${response.status}`);
      const config = await response.json();
      if (!active) return;
      configureEvents({ ...config, endpoint: collector, attributionEndpoint: `${collector}/attribution` });
      stop = startPageViews();
    } catch (error) {
      console.warn(`[events] collector_setup_failed: restore ${collector}/config and reload`, error);
    }
  })();
  return () => {
    active = false;
    stop();
  };
}
