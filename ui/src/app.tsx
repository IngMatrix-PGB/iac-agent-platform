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
              &gt;<span className="brand-caret">_</span>
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
        <div className="signature">
          <p className="signature-prompt" aria-hidden="true">
            ~/iac-agent <span className="signature-dollar">$</span> whoami
          </p>
          <p className="signature-line">
            <span className="signature-label">Designed and built by</span>
            <span className="signature-name">Pablo Galeana Bailey</span>
            <span className="signature-handle">Ing Matrix</span>
          </p>
        </div>
        <a
          className="signature-link"
          href="https://github.com/IngMatrix-PGB"
          aria-label="Pablo Galeana Bailey on GitHub"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path
              fill="currentColor"
              d="M12 .5a12 12 0 0 0-3.8 23.4c.6.1.8-.3.8-.6v-2c-3.3.7-4-1.6-4-1.6-.6-1.4-1.4-1.8-1.4-1.8-1.1-.8.1-.7.1-.7 1.2.1 1.9 1.3 1.9 1.3 1.1 1.9 2.9 1.3 3.6 1 .1-.8.4-1.3.8-1.6-2.7-.3-5.5-1.3-5.5-6 0-1.3.5-2.4 1.3-3.2-.1-.3-.6-1.6.1-3.2 0 0 1-.3 3.3 1.2a11.5 11.5 0 0 1 6 0C17.3 4.4 18.3 4.7 18.3 4.7c.7 1.6.2 2.9.1 3.2.8.8 1.3 1.9 1.3 3.2 0 4.7-2.8 5.7-5.5 6 .4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6A12 12 0 0 0 12 .5Z"
            />
          </svg>
          @IngMatrix-PGB
        </a>
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
