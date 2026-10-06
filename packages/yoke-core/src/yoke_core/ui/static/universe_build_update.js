// An open tab keeps its loaded assets until the person chooses to reload.
const CHECK_INTERVAL_MS = 60_000;

export function mountBuildUpdate(main, windowNode, options) {
  if (typeof windowNode.fetch !== "function") return () => {};
  const documentNode = main.ownerDocument;
  // Mount the empty live region before inserting its announcement.
  const status = documentNode.createElement("div");
  status.setAttribute("role", "status");
  main.parentNode.insertBefore(status, main);
  let noticeShown = false;
  function showNotice() {
    const banner = documentNode.createElement("div");
    banner.className = "build-update-banner";
    const message = documentNode.createElement("span");
    message.textContent = "A new version of Yoke is available.";
    const reload = documentNode.createElement("button");
    reload.type = "button";
    reload.textContent = "Reload";
    reload.addEventListener("click", () => windowNode.location.reload());
    banner.appendChild(message);
    banner.appendChild(reload);
    status.appendChild(banner);
    noticeShown = true;
  }
  let loadedBuild = String(options.runtimeIdentity?.build || "").trim();
  let active = true;
  let checking = false;
  let controller;
  async function check() {
    if (!active || checking || noticeShown || documentNode.visibilityState !== "visible") return;
    checking = true;
    controller = new windowNode.AbortController();
    const timeout = windowNode.setTimeout(() => controller.abort(), 10_000);
    try {
      const response = await windowNode.fetch("/served-build", {
        cache: "no-store", credentials: "same-origin", signal: controller.signal,
      });
      if (!response.ok) return;
      const build = (await response.text()).trim();
      if (!active || !build) return;
      if (!loadedBuild) loadedBuild = build;
      else if (build !== loadedBuild) showNotice();
    } catch { /* Unavailable identity leaves the page usable; later checks retry. */ }
    finally { windowNode.clearTimeout(timeout); checking = false; }
  }
  const onVisible = () => {
    if (documentNode.visibilityState === "visible") void check();
  };
  windowNode.addEventListener("focus", check);
  documentNode.addEventListener("visibilitychange", onVisible);
  const timer = windowNode.setInterval(check, CHECK_INTERVAL_MS);
  void check();
  return () => {
    active = false;
    controller?.abort();
    windowNode.clearInterval(timer);
    windowNode.removeEventListener("focus", check);
    documentNode.removeEventListener("visibilitychange", onVisible);
    status.parentNode?.removeChild(status);
  };
}
