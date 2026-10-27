import "@testing-library/jest-dom";
import { beforeEach, afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";
beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path) => ({
      ok: true,
      status: 200,
      json: async () =>
        path.includes("sync-exceptions")
          ? { results: [], count: 0 }
          : ["/documents/", "/compliance/", "/evc/", "/notifications/"].some(
                (part) => path.includes(part),
              )
            ? []
            : path.includes("/cases/")
              ? { results: [], count: 0, next: null, previous: null }
              : path.includes("/policy/")
                ? []
                : {
                    total_visible_cases: 0,
                    data_as_of: "2026-10-27T00:00:00Z",
                  },
    })),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
