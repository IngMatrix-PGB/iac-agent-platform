import type { ApiClient } from "./api/client";
import { HealthIndicator } from "./components/health-indicator";
import { ComposePage } from "./pages/compose-page";
import { RequestPage } from "./pages/request-page";
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
      <header className="shell-header">
        <h1>IaC Agent Platform</h1>
        <p>Local operator console. Review the server response before approving a request.</p>
        <HealthIndicator client={client} />
      </header>
      {route.name === "compose" ? <ComposePage client={client} navigate={navigate} /> : null}
      {route.name === "request" ? (
        <RequestPage client={client} requestId={route.requestId} />
      ) : null}
      {route.name === "unknown" ? <h2>Page not found.</h2> : null}
    </main>
  );
}
