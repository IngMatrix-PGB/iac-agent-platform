export const POLL_INTERVAL_MS = 5000;
export const POLL_MAX_ATTEMPTS = 12;

const POLLABLE = new Set(["pending", "running", "approved"]);

export function shouldPoll(status: string | null | undefined): boolean {
  return typeof status === "string" && POLLABLE.has(status);
}
