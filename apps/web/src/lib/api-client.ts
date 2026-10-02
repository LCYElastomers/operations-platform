// Browser requests use same-origin paths. The web server (and later Nginx)
// forwards /api/* to the FastAPI service, so no backend address or
// credentials ever reach client code.

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
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
