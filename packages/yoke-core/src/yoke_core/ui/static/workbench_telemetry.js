// Consent is a user choice. Acquisition and delivery use the installed Pack.
import { configureEvents, setConsent } from "./events.js";
import { startPageViews } from "./events_navigation.js";

const CONSENT_KEY = "yoke.analytics.consent";

export function mountWorkbenchTelemetry(root, windowNode = window) {
  const documentNode = root.ownerDocument;
  const control = documentNode.createElement("div");
  control.className = "workbench-telemetry";
  const button = documentNode.createElement("button");
  button.type = "button";
  button.textContent = "Analytics: off";
  button.setAttribute("aria-pressed", "false");
  button.title = "Choose whether to share page views and usage analytics. This does not affect using Yoke.";
  button.disabled = true;
  const status = documentNode.createElement("span");
  status.setAttribute("role", "status");
  control.appendChild(button);
  control.appendChild(status);
  root.appendChild(control);
  const stylesheet = documentNode.createElement("link");
  stylesheet.rel = "stylesheet";
  stylesheet.href = new URL("./workbench_telemetry.css", import.meta.url).href;
  documentNode.head.appendChild(stylesheet);
  let active = true;
  let allowed = false;
  let stop = () => {};

  const choose = async (value) => {
    button.disabled = true;
    allowed = value;
    try {
      // Persist only an explicitly granted preference, never visitor identity.
      if (value) windowNode.localStorage?.setItem(CONSENT_KEY, "granted");
      else windowNode.localStorage?.removeItem(CONSENT_KEY);
    } catch { /* Private storage does not prevent a per-mount choice. */ }
    await setConsent(value);
    if (active) {
      button.textContent = `Analytics: ${value ? "on" : "off"}`;
      button.setAttribute("aria-pressed", String(value));
      button.disabled = false;
    }
  };
  button.addEventListener("click", () => { void choose(!allowed); });

  void (async () => {
    try {
      const response = await windowNode.fetch("/api/events/config", { credentials: "same-origin" });
      if (!response.ok) throw new Error(`collector_configuration_refused: HTTP ${response.status}`);
      const config = await response.json();
      if (!active) return;
      configureEvents(config);
      stop = startPageViews();
      let remembered = false;
      try { remembered = windowNode.localStorage?.getItem(CONSENT_KEY) === "granted"; } catch {}
      if (remembered) await choose(true);
      else button.disabled = false;
    } catch (error) {
      console.warn("[events] collector_setup_failed: restore /api/events/config and reload", error);
      if (active) status.textContent = "Analytics unavailable. Reload to retry.";
    }
  })();
  return () => {
    active = false;
    stop();
    control.parentNode?.removeChild(control);
    stylesheet.parentNode?.removeChild(stylesheet);
  };
}
