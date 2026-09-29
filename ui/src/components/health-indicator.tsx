import { useEffect, useState } from "react";
import type { ApiClient } from "../api/client";

export function HealthIndicator({ client }: { client: ApiClient }) {
  const [health, setHealth] = useState("API process did not respond.");
  const [ready, setReady] = useState("Application process is not ready.");

  useEffect(() => {
    let cancelled = false;
    void client.health().then((result) => {
      if (cancelled) {
        return;
      }
      setHealth(
        result.kind === "success" && result.status === "ok"
          ? "API process responded."
          : "API process did not respond.",
      );
    });
    void client.ready().then((result) => {
      if (cancelled) {
        return;
      }
      setReady(
        result.kind === "success" && result.status === "ready"
          ? "Application process is ready to accept requests."
          : "Application process is not ready.",
      );
    });
    return () => {
      cancelled = true;
    };
  }, [client]);

  return (
    <section aria-label="Process status">
      <dl>
        <dt role="term">API</dt>
        <dd>{health}</dd>
        <dt role="term">Readiness</dt>
        <dd>{ready}</dd>
      </dl>
    </section>
  );
}
