import { useCallback, useEffect, useMemo, useState } from "react";
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
  const [focusId, setFocusId] = useState<"compose" | "requests" | null>(null);

  function openRegion(id: "compose" | "requests") {
    if (route.name !== "compose") {
      navigate("/");
    }
    setFocusId(id);
  }

  useEffect(() => {
    if (focusId === null || operatorClient === null) {
      return;
    }
    document.getElementById(focusId)?.focus();
    setFocusId(null);
  }, [focusId, operatorClient, route.name]);

  return (
    <main>
      <header className="shell-header">
        <div className="shell-bar">
          <div className="brand">
            <span className="brand-mark" aria-hidden="true">
              &gt;_
            </span>
            <h1>IaC Agent</h1>
            <p className="product-kicker">Infrastructure control plane</p>
          </div>
          <div className="shell-side">
          <nav className="shell-nav" aria-label="Primary">
            <a
              href="/#compose"
              aria-current={route.name === "compose" ? "page" : undefined}
              onClick={(event) => {
                event.preventDefault();
                openRegion("compose");
              }}
            >
              Compose
            </a>
            <a
              href="/#requests"
              onClick={(event) => {
                event.preventDefault();
                openRegion("requests");
              }}
            >
              Requests
            </a>
          </nav>
          <HealthIndicator client={client} />
          </div>
        </div>
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
          onBack={() => openRegion("requests")}
        />
      ) : null}
      {route.name === "unknown" ? <h2>Page not found.</h2> : null}
      <footer className="shell-footer">
        Powered by <a href="https://github.com/IngMatrix-PGB">Pablo Galeana Bailey</a>
      </footer>
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
      <p>This secret stays in this tab's memory. Reloading the page clears it.</p>
      <button className="button-primary" type="submit">Continue</button>
    </form>
  );
}
