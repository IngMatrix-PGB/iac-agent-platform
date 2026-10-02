import { useEffect, useRef } from "react";

export type NoticeTone = "config" | "error" | "conflict" | "missing";

export function noticeTone(error: string): NoticeTone {
  if (error === "capability_unavailable") {
    return "config";
  }
  if (error === "approval_conflict" || error === "request_exists") {
    return "conflict";
  }
  if (error === "request_not_found") {
    return "missing";
  }
  return "error";
}

const HEADING: Record<NoticeTone, string | null> = {
  config: "Not configured",
  error: null,
  conflict: null,
  missing: null,
};

export function ErrorBanner({ message, tone }: { message: string; tone: NoticeTone }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.focus();
  }, [message]);
  const heading = tone === "conflict" && message === "This request cannot accept that decision."
    ? "Approval conflict"
    : HEADING[tone];
  return (
    <div className={`notice-${tone}`} role="alert" tabIndex={-1} ref={ref}>
      {heading ? <h3>{heading}</h3> : null}
      <p>{message}</p>
    </div>
  );
}
