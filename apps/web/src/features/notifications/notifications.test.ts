import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api-client";

import { describeNotificationsError, notificationKeys } from "./api";
import { insertAtCursor } from "./notifications-shared";

describe("notificationKeys", () => {
  it("scopes overview and deliveries under notifications", () => {
    expect(notificationKeys.overview(7)).toEqual(["notifications", "overview", 7]);
    expect(notificationKeys.deliveries({ status: "failed", limit: 50, offset: 0 })[0]).toBe(
      "notifications",
    );
  });
});

describe("describeNotificationsError", () => {
  it("surfaces API detail messages", () => {
    expect(
      describeNotificationsError(
        new ApiError(422, "fail", { error: "validation_failed", message: "Template validation failed." }),
      ),
    ).toBe("Template validation failed.");
  });

  it("maps common statuses", () => {
    expect(describeNotificationsError(new ApiError(403, "fail"))).toMatch(/permission/i);
    expect(describeNotificationsError(new ApiError(503, "fail"))).toMatch(/unavailable/i);
    expect(describeNotificationsError(new Error("network"))).toMatch(/could not be reached/i);
  });
});

describe("insertAtCursor", () => {
  it("inserts a variable token at the caret", () => {
    expect(insertAtCursor("Hello  world", "{{action.title}}", 6, 6)).toBe(
      "Hello {{action.title}} world",
    );
  });

  it("replaces a selection", () => {
    expect(insertAtCursor("aaXXXbb", "{{x}}", 2, 5)).toBe("aa{{x}}bb");
  });
});

describe("delivery query parameter names", () => {
  it("uses camelCase query keys expected by the API", () => {
    const params = new URLSearchParams();
    params.set("status", "failed");
    params.set("fromDate", "2026-01-01");
    params.set("eventTypeCode", "psm.action.assigned");
    params.set("workflowId", "3");
    expect(params.get("fromDate")).toBe("2026-01-01");
    expect(params.get("eventTypeCode")).toBe("psm.action.assigned");
    expect(params.get("workflowId")).toBe("3");
  });
});
