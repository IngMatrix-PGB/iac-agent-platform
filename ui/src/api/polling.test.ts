import { describe, expect, it } from "vitest";
import { POLL_INTERVAL_MS, POLL_MAX_ATTEMPTS, shouldPoll } from "./polling";

describe("polling policy", () => {
  it("refreshes only pending, running, and approved", () => {
    expect(POLL_INTERVAL_MS).toBe(5000);
    expect(POLL_MAX_ATTEMPTS).toBe(12);
    expect(shouldPoll("pending")).toBe(true);
    expect(shouldPoll("running")).toBe(true);
    expect(shouldPoll("approved")).toBe(true);
    for (const status of [
      "awaiting_approval",
      "rejected",
      "blocked",
      "error",
      "pr_created",
      null,
      "clarification_required",
    ]) {
      expect(shouldPoll(status)).toBe(false);
    }
  });
});
