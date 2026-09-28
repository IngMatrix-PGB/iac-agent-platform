import type { ApiClient } from "./api/client";
import { HealthIndicator } from "./components/health-indicator";
import { ComposePage } from "./pages/compose-page";
import { parseRoute } from "./router";
import "./styles.css";

export function App({
  client,
  navigate,
  pathname,
}: {
  client: ApiClient;
  navigate: (path: string) => void;
  pathname?: string;
}) {
  const route = parseRoute(pathname ?? window.location.pathname);
  return (
    <main>
      <h1>IaC Agent Platform</h1>
      <HealthIndicator client={client} />
      {route.name === "compose" ? <ComposePage client={client} navigate={navigate} /> : null}
      {route.name === "request" ? <p>Request {route.requestId}</p> : null}
      {route.name === "unknown" ? <p>Page not found.</p> : null}
    </main>
  );
}
