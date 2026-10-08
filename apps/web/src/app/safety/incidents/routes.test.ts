import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import nextConfig from "../../../../next.config";

const SRC = path.resolve(import.meta.dirname, "../../..");
const OLD_ROUTE = "/safety/incidents/analytics";

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return /\.(ts|tsx)$/.test(entry.name) && !/\.test\.(ts|tsx)$/.test(entry.name) ? [full] : [];
  });
}

describe("Incident & Near Miss routes", () => {
  it("redirects the retired Analytics page to the Dashboard", async () => {
    const redirects = (await nextConfig.redirects?.()) ?? [];
    expect(redirects.filter((r) => r.source === OLD_ROUTE)).toEqual([
      { source: OLD_ROUTE, destination: "/safety/incidents/dashboard", permanent: true },
    ]);
  });

  it("renders the Dashboard page and no separate Analytics page", () => {
    expect(existsSync(path.join(SRC, "app/safety/incidents/dashboard/page.tsx"))).toBe(true);
    expect(existsSync(path.join(SRC, "app/safety/incidents/analytics"))).toBe(false);
  });

  it("has no application link to the retired Analytics page", () => {
    // The Incident Analytics API (/api/v1/safety/incidents/analytics) is not a page link.
    const stale = sourceFiles(SRC).filter((file) =>
      readFileSync(file, "utf8")
        .split("\n")
        .some((line) => line.includes(OLD_ROUTE) && !line.includes(`/api/v1${OLD_ROUTE}`)),
    );
    expect(stale).toEqual([]);
  });
});
