import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ApiClient } from "./api/client";
import { App } from "./app";

function createOperatorClient(operatorSecret: string): ApiClient {
  return new ApiClient(globalThis.fetch, { operatorSecret });
}

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App
        client={new ApiClient()}
        createClient={createOperatorClient}
        navigate={(path) => {
          window.location.assign(path);
        }}
      />
    </StrictMode>,
  );
}
