import { useState } from "react";
import type { RequestResponse } from "../api/types";
import { AuthoritativeValue, statusLabel } from "./authoritative-value";

function CopyRequestId({ requestId }: { requestId: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(requestId);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  return (
    <button className="copy-id" type="button" aria-label="Copy request id" onClick={() => void copy()}>
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <rect x="9" y="9" width="11" height="11" rx="2" />
        <path d="M5 15V6a2 2 0 0 1 2-2h9" />
      </svg>
      {copied ? <span role="status">copied</span> : null}
    </button>
  );
}

export function RequestSummary({ body }: { body: RequestResponse }) {
  const name = body.resolution.name;
  const architecture = body.resolution.architecture;
  const components = body.resolution.components ?? [];
  return (
    <section className="request-head" aria-labelledby="request-review-heading">
      <div className="request-title">
        <h2 id="request-review-heading">{name ?? body.request_id}</h2>
        {name ? <p className="meta">{body.request_id}</p> : null}
        <CopyRequestId requestId={body.request_id} />
      </div>
      {architecture ? (
        <p className="architecture-line" title={architecture}>
          {statusLabel(architecture).replaceAll(" + ", " → ")}
        </p>
      ) : null}
      {body.intent || components.length > 0 ? (
        <details className="intent-details">
          <summary>intent</summary>
          {body.intent ? (
            <dl>
              <AuthoritativeValue label="Workload" value={body.intent.workload_type} />
              <AuthoritativeValue label="Interaction" value={body.intent.interaction_pattern} />
              <div>
                <dt role="term" aria-label="Capabilities">
                  Capabilities
                </dt>
                <dd>{body.intent.capabilities.join(" ")}</dd>
              </div>
            </dl>
          ) : null}
          {components.length > 0 ? (
            <>
              <h4>Components</h4>
              <ul>
                {components.map((component) => (
                  <li key={`${component.role}:${component.name}`}>
                    <span>{component.role}</span> <span>{component.name}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </details>
      ) : null}
    </section>
  );
}
