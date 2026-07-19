/**
 * Shared event-property helpers. See events/README.md.
 */

// ---------------------------------------------------------------------------
// Property Group Builders
// ---------------------------------------------------------------------------

/**
 * Resolve system properties from environment.
 *
 * Uses NEXT_PUBLIC_ prefixed env vars for Next.js client-side access.
 */
export function getSystemProps(): Record<string, unknown> {
  return {
    environment: process.env.NEXT_PUBLIC_APP_ENV ?? 'development',
    service: 'web',
    service_version: process.env.NEXT_PUBLIC_APP_VERSION ?? null,
    project: process.env.NEXT_PUBLIC_PROJECT ?? '{{project_name}}',
  };
}

/**
 * Build session properties.
 *
 * Generates a session ID on first call and persists it in sessionStorage.
 * The session_start_time is captured once when the session ID is created.
 */
export function getSessionProps(): Record<string, unknown> {
  let sessionId = sessionStorage.getItem('event_session_id');
  if (!sessionId) {
    sessionId = crypto.randomUUID();
    sessionStorage.setItem('event_session_id', sessionId);
    sessionStorage.setItem(
      'event_session_start',
      new Date().toISOString()
    );
  }
  return {
    session_id: sessionId,
    session_start_time:
      sessionStorage.getItem('event_session_start') ?? null,
  };
}

/**
 * Build organization properties. Authenticated receivers stamp actor_id
 * server-side; a browser event never claims engine identity for itself.
 */
export function getOrgProps(
  orgId?: string
): Record<string, unknown> {
  return {
    org_id: orgId ?? null,
    org_name: null,
    org_plan: null,
  };
}

/**
 * Build page properties from the current browser location.
 */
export function getPageProps(): Record<string, unknown> {
  return {
    page_url: window.location.href,
    page_path: window.location.pathname,
    page_title: document.title,
    referrer: document.referrer || null,
  };
}

/**
 * Build device properties by parsing the user agent string.
 */
export function getDeviceProps(): Record<string, unknown> {
  const ua = navigator.userAgent;
  return {
    user_agent: ua,
    browser: parseBrowser(ua),
    os: parseOS(ua),
    device_type: detectDeviceType(),
  };
}

// ---------------------------------------------------------------------------
// Device parsing helpers (used by getDeviceProps)
// ---------------------------------------------------------------------------

/**
 * Parse browser name and version from user agent string.
 */
function parseBrowser(ua: string): string {
  if (ua.includes('Chrome'))
    return `Chrome ${ua.match(/Chrome\/([\d.]+)/)?.[1] ?? ''}`.trim();
  if (ua.includes('Firefox'))
    return `Firefox ${ua.match(/Firefox\/([\d.]+)/)?.[1] ?? ''}`.trim();
  if (ua.includes('Safari'))
    return `Safari ${ua.match(/Version\/([\d.]+)/)?.[1] ?? ''}`.trim();
  return 'Unknown';
}

/**
 * Parse OS name from user agent string.
 */
function parseOS(ua: string): string {
  if (ua.includes('Mac OS X'))
    return `macOS ${ua.match(/Mac OS X ([\d_]+)/)?.[1]?.replace(/_/g, '.') ?? ''}`.trim();
  if (ua.includes('Windows')) return 'Windows';
  if (ua.includes('Linux')) return 'Linux';
  if (ua.includes('Android')) return 'Android';
  if (ua.includes('iPhone') || ua.includes('iPad')) return 'iOS';
  return 'Unknown';
}

/**
 * Detect device type from viewport width.
 */
function detectDeviceType(): string {
  if (typeof window === 'undefined') return 'unknown';
  const width = window.innerWidth;
  if (width < 768) return 'mobile';
  if (width < 1024) return 'tablet';
  return 'desktop';
}
