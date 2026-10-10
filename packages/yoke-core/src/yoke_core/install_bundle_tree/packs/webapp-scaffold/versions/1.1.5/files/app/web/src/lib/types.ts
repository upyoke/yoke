/**
 * Core TypeScript types for {{project_display_name}}.
 * Contains only generic auth/multi-tenant types.
 * Add domain-specific types as your project grows.
 */

// -- Auth --

export interface Org {
  id: number;
  name: string;
  slug: string;
  role: string;
}

export interface User {
  id: number;
  email: string;
  name: string | null;
  role: string;
  orgs?: Org[];
}

export interface Session {
  id: string;
  user_id: number;
  expires_at: string;
}
