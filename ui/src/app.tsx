import { useCallback, useMemo, useState } from "react";
import type { ApiClient } from "./api/client";
import { HealthIndicator } from "./components/health-indicator";
import { ComposePage } from "./pages/compose-page";
import { RequestPage } from "./pages/request-page";
import { parseRoute } from "./router";
import "./styles.css";

export function App({
  client,
  createClient,
  navigate,
  pathname,
}: {
  client: ApiClient;
  createClient?: (operatorSecret: string) => ApiClient;
  navigate: (path: string) => void;
  pathname?: string;
}) {
  const [secret, setSecret] = useState<string | null>(null);
  const route = parseRoute(pathname ?? window.location.pathname);
  const operatorClient = useMemo(() => {
    if (secret === null) {
      return null;
    }
    return createClient ? createClient(secret) : client;
  }, [client, createClient, secret]);
  const clearSecret = useCallback(() => setSecret(null), []);

  return (
    <main>
      <header className="shell-header">
        <h1>IaC Agent Platform</h1>
        <p>Local operator console. Review the server response before approving a request.</p>
        <HealthIndicator client={client} />
      </header>
      {operatorClient === null ? <OperatorSecretForm onContinue={setSecret} /> : null}
      {operatorClient !== null && route.name === "compose" ? (
        <ComposePage client={operatorClient} navigate={navigate} onUnauthenticated={clearSecret} />
      ) : null}
      {operatorClient !== null && route.name === "request" ? (
        <RequestPage
          client={operatorClient}
          requestId={route.requestId}
          onUnauthenticated={clearSecret}
        />
      ) : null}
      {route.name === "unknown" ? <h2>Page not found.</h2> : null}
    </main>
  );
}

function OperatorSecretForm({ onContinue }: { onContinue: (secret: string) => void }) {
  const [draft, setDraft] = useState("");

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (!draft.trim()) {
          return;
        }
        onContinue(draft);
      }}
    >
      <label htmlFor="operator-secret">Operator secret</label>
      <input
        id="operator-secret"
        type="password"
        name="operator-secret"
        autoComplete="off"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
      />
      <p>Enter the operator secret for this session. Reloading clears it.</p>
      <button type="submit">Continue</button>
    </form>
  );
}
