import { el } from "./universe_view_support.js";

const SELF_HOST_GUIDE = "https://github.com/upyoke/yoke/blob/main/docs/self-host.md";

export function localReachabilityNotice(documentNode, { variant = "full" } = {}) {
  const notice = el(documentNode, "div", "local-reachability-notice");
  const sentence = el(documentNode, "p", "machine-approval-lede");
  if (variant === "token") {
    sentence.appendChild(documentNode.createTextNode("This token works on this computer only. A token does not make this local universe reachable from another computer. To share it, set up a team server with "));
  } else {
    sentence.appendChild(el(documentNode, "strong", null, "Reachable here only."));
    sentence.appendChild(documentNode.createTextNode(" This universe runs on this computer. Other people and computers can't connect to it. To work with a team or a second machine, set up a team server: "));
  }
  sentence.appendChild(el(documentNode, "code", null, "yoke self-host init"));
  sentence.appendChild(documentNode.createTextNode("."));
  notice.appendChild(sentence);
  const link = el(documentNode, "a", "app-footer-link", "Self-host guide →");
  link.href = SELF_HOST_GUIDE;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  notice.appendChild(link);
  return notice;
}
