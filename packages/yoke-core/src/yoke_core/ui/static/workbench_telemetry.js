// Workbench page views and usage analytics run from mount, through the installed Pack.
import { configureEvents } from "./events.js";
import { startPageViews } from "./events_navigation.js";

export function mountWorkbenchTelemetry(windowNode = window) {
  let active = true;
  let stop = () => {};
  void (async () => {
    try {
      const response = await windowNode.fetch("/api/events/config", { credentials: "same-origin" });
      if (!response.ok) throw new Error(`collector_configuration_refused: HTTP ${response.status}`);
      const config = await response.json();
      if (!active) return;
      configureEvents(config);
      stop = startPageViews();
    } catch (error) {
      console.warn("[events] collector_setup_failed: restore /api/events/config and reload", error);
    }
  })();
  return () => {
    active = false;
    stop();
  };
}
