import type { UniverseSectionContext } from "./universe-app.js";
/** Host pages are unscoped; detail is the decoded optional route segment. */
export interface UniverseHostPageContext extends UniverseSectionContext {
    readonly detail: string | null;
}
export interface UniverseHostNavPage {
    /** Lowercase slug, unique across groups and distinct from Yoke view ids. */
    readonly id: string;
    readonly label: string;
    /** Existing universe_nav_icons.js key; unknown keys leave the icon slot blank. */
    readonly icon?: string;
    readonly content: Element | ((context: UniverseHostPageContext) => Element | null | undefined);
}
/** Hosts omit groups the viewer may not access; empty groups are hidden. */
export interface UniverseHostNavGroup {
    readonly id: string;
    readonly label: string;
    /** Starts closed; remembers state by group id (1–64 lowercase slug characters). */
    readonly collapsible?: boolean;
    readonly pages: readonly UniverseHostNavPage[];
}
