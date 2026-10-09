import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, APP_HEADER, apiGet, apiSend, isPublicPath, safeNextPath } from "./api-client";

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

  it("marks every write as coming from the application", async () => {
    const fetchMock = stubFetch(new Response(null, { status: 204 }));

    await apiSend("POST", "/api/v1/x", { a: 1 });
    await apiSend("DELETE", "/api/v1/x/1");
    for (const call of fetchMock.mock.calls as unknown as [string, RequestInit][]) {
      expect(call[1].headers).toMatchObject(APP_HEADER);
    }
  });
});

describe("expired sessions", () => {
  function stubLocation(pathname: string, search = "") {
    const assign = vi.fn();
    vi.stubGlobal("window", { location: { pathname, search, assign } });
    return assign;
  }

  it("sends the user to sign in and back to the page they were on", async () => {
    const assign = stubLocation("/quality/cars/register", "?status=open");
    stubFetch(Response.json({ detail: { error: "authentication_required" } }, { status: 401 }));

    await expect(apiGet("/api/v1/quality/cars")).rejects.toBeInstanceOf(ApiError);
    expect(assign).toHaveBeenCalledWith("/login?next=%2Fquality%2Fcars%2Fregister%3Fstatus%3Dopen");
  });

  it("does not redirect for a failed sign-in or on the sign-in page", async () => {
    const assign = stubLocation("/quality");
    stubFetch(Response.json({ detail: { error: "sign_in_failed" } }, { status: 401 }));
    await expect(apiSend("POST", "/api/v1/auth/sign-in", {})).rejects.toBeInstanceOf(ApiError);

    stubLocation("/login");
    stubFetch(Response.json({}, { status: 401 }));
    await expect(apiGet("/api/v1/auth/me")).rejects.toBeInstanceOf(ApiError);
    expect(assign).not.toHaveBeenCalled();
  });

  it("does not treat a missing permission as an expired session", async () => {
    const assign = stubLocation("/admin/users");
    stubFetch(Response.json({ detail: { error: "permission_denied" } }, { status: 403 }));

    const error = await apiGet("/api/v1/admin/users").catch((e: unknown) => e);
    expect((error as ApiError).status).toBe(403);
    expect(assign).not.toHaveBeenCalled();
  });
});

describe("safeNextPath", () => {
  it("keeps same-site paths only", () => {
    expect(safeNextPath("/quality/cars?status=open")).toBe("/quality/cars?status=open");
    expect(safeNextPath(null)).toBe("/");
    expect(safeNextPath("https://evil.example/")).toBe("/");
    expect(safeNextPath("//evil.example/")).toBe("/");
    expect(safeNextPath("/\\evil.example/")).toBe("/");
    expect(safeNextPath("javascript:alert(1)")).toBe("/");
  });

  it("never returns to the sign-in pages", () => {
    expect(safeNextPath("/login?next=/x")).toBe("/");
    expect(safeNextPath("/setup-password#token=abc")).toBe("/");
    expect(isPublicPath("/login")).toBe(true);
    expect(isPublicPath("/loginx")).toBe(false);
  });
});
