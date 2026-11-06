/**
 * Server-side bot, browser, OS and device classification for collected events.
 * The collector is the only authority: it parses the request User-Agent with
 * Bowser and lets the default User-Agent Client Hints override it. Viewport
 * size is a layout signal and never decides device type.
 */
import Bowser from 'bowser';
import { isBot } from './events_attribution.ts';

const MOBILE_OS = new Set(['Android', 'iOS', 'Windows Phone', 'KaiOS']);

function hint(headers: Headers, name: string): string | null {
  const value = headers.get(name);
  return value ? value.trim().replace(/^"|"$/g, '') : null;
}

function deviceType(platformType: string | undefined, os: string | null, mobile: string | null): string {
  if (mobile === '?1') return 'mobile';
  if (platformType === 'tablet') return 'tablet';
  if (mobile === null && (platformType === 'mobile' || MOBILE_OS.has(os || ''))) return 'mobile';
  return 'desktop';
}

export function deviceProps(headers: Headers): Record<string, string | boolean | null> {
  const userAgent = headers.get('User-Agent') || '';
  const mobile = hint(headers, 'Sec-CH-UA-Mobile');
  const parsed = userAgent ? Bowser.parse(userAgent) : null;
  const os = hint(headers, 'Sec-CH-UA-Platform') || parsed?.os.name || null;
  const props: Record<string, string | boolean | null> = {
    is_bot: isBot(userAgent),
    browser: parsed?.browser.name || null,
    browser_version: parsed?.browser.version || null,
    os,
    device_type: parsed || mobile !== null ? deviceType(parsed?.platform.type, os, mobile) : null,
  };
  const iosVersion = userAgent.match(/(?:CPU (?:iPhone )?OS|iPhone OS) (\d+(?:_\d+)*)/);
  if (iosVersion) props.os_version = iosVersion[1].replaceAll('_', '.');
  return props;
}

const stringFacts = ['os_version', 'device_model', 'cpu_architecture', 'cpu_bitness', 'gpu_renderer', 'connection_type'];
const numberFacts: Record<string, [number, number, boolean]> = {
  cpu_cores: [1, 1024, true], device_memory_gb: [0, 1024, false], pixel_ratio: [0, 16, false],
  touch_points: [0, 256, true], color_depth: [1, 64, true], connection_downlink_mbps: [0, 100000, false],
};
export function mergeDeviceProps(event: Record<string, unknown>, device: Record<string, unknown>): void {
  for (const name of stringFacts) {
    const value = event[name];
    if (name in event && !(typeof value === 'string' && value.length > 0 && Array.from(value).length <= 128)) delete event[name];
  }
  for (const [name, [low, high, integer]] of Object.entries(numberFacts)) {
    if (!(name in event)) continue;
    const value = event[name];
    if (!(typeof value === 'number' && Number.isFinite(value) && value >= low && value <= high &&
        (!integer || Number.isInteger(value)) && (!['device_memory_gb', 'pixel_ratio'].includes(name) || value > 0))) delete event[name];
  }
  Object.assign(event, device);
}
