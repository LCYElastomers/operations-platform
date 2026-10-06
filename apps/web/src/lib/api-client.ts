// Browser requests use same-origin paths. The web server (and later Nginx)
// forwards /api/* to the FastAPI service, so no backend address or
// credentials ever reach client code.

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

export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    method: "GET",
    headers: { Accept: "application/json", ...init?.headers },
  });

  if (!response.ok) {
    throw new ApiError(response.status, `GET ${path} failed: ${response.status}`);
  }

  return (await response.json()) as T;
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

export async function apiSend<T>(
  method: "POST" | "PUT" | "PATCH" | "DELETE",
  path: string,
  body: unknown,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(path, {
    ...init,
    method,
    headers: { Accept: "application/json", "Content-Type": "application/json", ...init?.headers },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new ApiError(
      response.status,
      `${method} ${path} failed: ${response.status}`,
      await readErrorDetail(response),
    );
  }

  return (await response.json()) as T;
}
