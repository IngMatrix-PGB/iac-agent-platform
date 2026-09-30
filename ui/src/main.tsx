import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { ApiClient } from "./api/client";
import { App } from "./app";

function createOperatorClient(operatorSecret: string): ApiClient {
  return new ApiClient(globalThis.fetch, { operatorSecret });
}

function OperatorShell() {
  const [pathname, setPathname] = useState(() => window.location.pathname);
  const [probeClient] = useState(() => new ApiClient());
  useEffect(() => {
    const sync = () => setPathname(window.location.pathname);
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);
  return (
    <App
      client={probeClient}
      createClient={createOperatorClient}
      pathname={pathname}
      navigate={(path) => {
        window.history.pushState(null, "", path);
        setPathname(path);
      }}
    />
  );
}

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <OperatorShell />
    </StrictMode>,
  );
}
