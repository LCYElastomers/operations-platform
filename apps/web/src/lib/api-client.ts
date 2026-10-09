// Browser requests use same-origin paths. The web server (and later Nginx)
// forwards /api/* to the FastAPI service, so no backend address or
// credentials ever reach client code. The session is an HttpOnly cookie the
// browser sends with every same-origin request; scripts never see it.

/** FastAPI error bodies have the form {"detail": {"error": "<code>", "message": "..."}}. */
export type ApiErrorDetail = { error?: string; message?: string; [key: string]: unknown };

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly detail?: ApiErrorDetail,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * Sent with every write. The API refuses writes that carry the session cookie
 * without it, so another site cannot make a signed-in browser change data.
 */
export const APP_HEADER = { "X-Requested-With": "operations-platform" } as const;

/** Pages anyone may open; a 401 there is an answer, not a reason to redirect. */
export const PUBLIC_PATHS = ["/login", "/setup-password"] as const;

export function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some((path) => pathname === path || pathname.startsWith(`${path}/`));
}

/** A same-site path to return to after signing in; anything else becomes "/". */
export function safeNextPath(value: string | null | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) return "/";
  return isPublicPath(value.split(/[?#]/, 1)[0]) ? "/" : value;
}

/** Sign-in endpoints answer 401 for wrong credentials; that is not an expired session. */
function isAuthEndpoint(path: string) {
  return path.startsWith("/api/v1/auth/");
}

/** The session ended (signed out elsewhere, expired, or the user was deactivated). */
function onUnauthorized(path: string) {
  if (typeof window === "undefined" || isAuthEndpoint(path)) return;
  const { pathname, search } = window.location;
  if (isPublicPath(pathname)) return;
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- outside React; a full load drops the ended session's cached data
  window.location.assign(`/login?next=${encodeURIComponent(pathname + search)}`);
}

async function readErrorDetail(response: Response): Promise<ApiErrorDetail | undefined> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return body.detail && typeof body.detail === "object" && !Array.isArray(body.detail)
      ? (body.detail as ApiErrorDetail)
      : undefined;
  } catch {
    return undefined;
  }
}

export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    method: "GET",
    headers: { Accept: "application/json", ...init?.headers },
  });

  if (!response.ok) {
    if (response.status === 401) onUnauthorized(path);
    throw new ApiError(response.status, `GET ${path} failed: ${response.status}`, await readErrorDetail(response));
  }

  return (await response.json()) as T;
}

/** Sends a JSON request. A 204 No Content response resolves to undefined. */
export async function apiSend<T>(
  method: "POST" | "PUT" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(path, {
    ...init,
    method,
    headers: {
      Accept: "application/json",
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      ...APP_HEADER,
      ...init?.headers,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!response.ok) {
    if (response.status === 401) onUnauthorized(path);
    throw new ApiError(
      response.status,
      `${method} ${path} failed: ${response.status}`,
      await readErrorDetail(response),
    );
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
