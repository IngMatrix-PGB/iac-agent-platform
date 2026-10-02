import { useEffect, useState } from "react";
import type { ApiClient, ProbeResult } from "../api/client";

function runtimeMark(health: ProbeResult, ready: ProbeResult): string {
  if (!(health.kind === "success" && health.status === "ok")) {
    return "Runtime unreachable";
  }
  if (ready.kind === "success" && ready.status === "ready") {
    return "Runtime ready";
  }
  return "Runtime not ready";
}

export function HealthIndicator({ client }: { client: ApiClient }) {
  const [text, setText] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([client.health(), client.ready()]).then(([health, ready]) => {
      if (cancelled) {
        return;
      }
      setText(runtimeMark(health, ready));
    });
    return () => {
      cancelled = true;
    };
  }, [client]);

  const tone =
    text === "Runtime ready" ? "ready" : text === "Runtime not ready" ? "closed" : "unreachable";

  return (
    <section aria-label="Process status">
      {text ? (
        <p className="runtime-mark">
          <span className={`runtime-dot runtime-dot-${tone}`} aria-hidden="true" />
          {text}
        </p>
      ) : null}
    </section>
  );
}
