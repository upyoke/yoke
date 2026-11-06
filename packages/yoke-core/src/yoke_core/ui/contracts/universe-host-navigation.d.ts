import type { UniverseSectionContext } from "./universe-app.js";
/** Host pages are unscoped; detail is the decoded optional route segment. */
export interface UniverseHostPageContext extends UniverseSectionContext {
    readonly detail: string | null;
}
export interface UniverseHostNavPage {
    /** Lowercase slug, unique across groups and distinct from Yoke view ids. */
    readonly id: string;
    readonly label: string;
    readonly content: Element | ((context: UniverseHostPageContext) => Element | null | undefined);
}
/** Hosts omit groups the viewer may not access; empty groups are hidden. */
export interface UniverseHostNavGroup {
    readonly id: string;
    readonly label: string;
    readonly pages: readonly UniverseHostNavPage[];
}
