import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import nextConfig from "../../../next.config";

const SRC = path.resolve(import.meta.dirname, "../..");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return /\.(ts|tsx)$/.test(entry.name) && !/\.test\.(ts|tsx)$/.test(entry.name) ? [full] : [];
  });
}

describe("retired Supervisor Safety Contacts", () => {
  it("redirects every old route to Safety", async () => {
    const redirects = (await nextConfig.redirects?.()) ?? [];
    expect(redirects.filter((r) => r.source.startsWith("/safety/contacts"))).toEqual([
      { source: "/safety/contacts/:path*", destination: "/safety", permanent: false },
    ]);
  });

  it("has no page or feature code", () => {
    expect(existsSync(path.join(SRC, "app/safety/contacts"))).toBe(false);
    expect(existsSync(path.join(SRC, "features/safety/contacts"))).toBe(false);
  });

  it("is not linked or called anywhere in the application", () => {
    const stale = sourceFiles(SRC).filter((file) =>
      /\/safety\/contacts|Supervisor Safety Contact/i.test(readFileSync(file, "utf8")),
    );
    expect(stale).toEqual([]);
  });
});
