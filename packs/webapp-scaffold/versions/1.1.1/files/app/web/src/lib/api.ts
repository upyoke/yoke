/**
 * API client for {{project_display_name}}.
 *
 * All requests go to /api/* which Next.js rewrites to the FastAPI backend.
 * Response format: { status: "ok", data: T }
 * Error format: FastAPI uses { detail: { code, message } }
 */

export class ApiError extends Error {
  code: string;
  status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let code = "ERR_UNKNOWN";
    let message = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      // FastAPI returns { detail: { code, message } }
      const err = body.error || body.detail;
      if (err && typeof err === "object") {
        code = err.code || code;
        message = err.message || message;
      }
    } catch {
      // response body wasn't JSON
    }
    throw new ApiError(code, message, res.status);
  }
  const body = await res.json();
  return body.data as T;
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(path, { credentials: "include" });
  return handleResponse<T>(res);
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  return handleResponse<T>(res);
}

export async function apiPut<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  return handleResponse<T>(res);
}

export async function apiDelete<T>(path: string): Promise<T> {
  const res = await fetch(path, {
    method: "DELETE",
    credentials: "include",
  });
  return handleResponse<T>(res);
}
