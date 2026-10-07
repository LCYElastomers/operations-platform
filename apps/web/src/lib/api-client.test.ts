import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiSend } from "./api-client";

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubFetch(response: Response) {
  const fetchMock = vi.fn(async () => response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("apiSend", () => {
  it("sends JSON and returns the parsed body", async () => {
    const fetchMock = stubFetch(Response.json({ id: 1 }, { status: 201 }));

    await expect(apiSend("POST", "/api/v1/x", { a: 1 })).resolves.toEqual({ id: 1 });
    const init = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init[1].body).toBe('{"a":1}');
    expect(init[1].headers).toMatchObject({ "Content-Type": "application/json" });
  });

  it("returns undefined for 204 No Content and sends no body without one", async () => {
    const fetchMock = stubFetch(new Response(null, { status: 204 }));

    await expect(apiSend("DELETE", "/api/v1/x/1")).resolves.toBeUndefined();
    const init = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init[1].body).toBeUndefined();
    expect(init[1].headers).not.toHaveProperty("Content-Type");
  });

  it("raises ApiError with the error detail", async () => {
    stubFetch(Response.json({ detail: { error: "edit_conflict", message: "Changed" } }, { status: 409 }));

    const error = await apiSend("PUT", "/api/v1/x/1", {}).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(409);
    expect((error as ApiError).detail?.error).toBe("edit_conflict");
  });
});
