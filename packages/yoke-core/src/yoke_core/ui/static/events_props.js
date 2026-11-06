// Generated from the installed structured-events Pack; run build_frontend_events.
import { instantFromDate } from "./events_timestamps.mjs";
import { sanitizePath, sanitizeUrl, isBot } from "./events_attribution.js";

let sessionId                = null;
let started                = null;
export function getSystemProps()                          {
  return { project: 'yoke', service: 'web' };
}
export function getSessionProps()                          {
  if (!sessionId) { sessionId = crypto.randomUUID(); started = instantFromDate(new Date(Date.now())); }
  return { session_id: sessionId, session_start_time: started };
}
export function getOrgProps(orgId         )                          {
  // Authenticated receivers stamp actor_id and authorize org context server-side.
  return { org_id: orgId ?? null };
}
export function getPageProps()                          {
  return {
    page_url: sanitizeUrl(window.location.href), page_path: sanitizePath(window.location.pathname),
    page_title: document.title, referrer: sanitizeUrl(document.referrer),
  };
}
                                    
                        
                                                             
                                                                                              
  
const hintProps                          = {};
const hintNames                         = {
  platformVersion: 'os_version', model: 'device_model', architecture: 'cpu_architecture', bitness: 'cpu_bitness',
};
if (typeof navigator !== 'undefined') {
  try {
    void (navigator                   ).userAgentData?.getHighEntropyValues(Object.keys(hintNames)).then(values => {
      for (const [name, field] of Object.entries(hintNames)) {
        if (typeof values[name] === 'string' && values[name]) hintProps[field] = values[name];
      }
    }).catch(() => {});
  } catch { /* Optional hints never prevent an event. */ }
}
export function fillDeviceHints(event                         )       {
  for (const [name, value] of Object.entries(hintProps)) {
    if (!(name in event)) event[name] = value;
  }
}
let rendererRead = false;
let renderer                    ;
function gpuRenderer()                     {
  if (!rendererRead) {
    rendererRead = true;
    try {
      const gl = document.createElement('canvas').getContext('webgl');
      const extension = gl?.getExtension('WEBGL_debug_renderer_info');
      const value = extension && gl?.getParameter(extension.UNMASKED_RENDERER_WEBGL);
      if (typeof value === 'string' && value) renderer = value;
      gl?.getExtension('WEBGL_lose_context')?.loseContext();
    } catch { /* Unavailable WebGL leaves the renderer absent. */ }
  }
  return renderer;
}
export function getDeviceProps()                          {
  const nav = navigator                   ;
  const props                          = {
    user_agent: nav.userAgent, is_bot: isBot(nav.userAgent), language: nav.language,
    time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    screen: `${window.screen.width}x${window.screen.height}`,
    viewport: `${window.innerWidth}x${window.innerHeight}`,
  };
  const facts                          = {
    cpu_cores: nav.hardwareConcurrency, device_memory_gb: nav.deviceMemory,
    pixel_ratio: window.devicePixelRatio, color_depth: window.screen.colorDepth,
    touch_points: nav.maxTouchPoints, gpu_renderer: gpuRenderer(),
    connection_type: nav.connection?.effectiveType, connection_downlink_mbps: nav.connection?.downlink,
  };
  const bounds                                            = {
    cpu_cores: [1, 1024, true], device_memory_gb: [Number.MIN_VALUE, 1024, false],
    pixel_ratio: [Number.MIN_VALUE, 16, false], color_depth: [1, 64, true],
    touch_points: [0, 256, true], connection_downlink_mbps: [0, 100000, false],
  };
  for (const [name, value] of Object.entries(facts)) {
    const bound = bounds[name];
    if ((typeof value === 'number' && bound && Number.isFinite(value) && value >= bound[0] && value <= bound[1] && (!bound[2] || Number.isInteger(value))) ||
        (typeof value === 'string' && value)) props[name] = value;
  }
  fillDeviceHints(props);
  return props;
}
