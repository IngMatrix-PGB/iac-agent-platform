import type { RequestResponse } from "../api/types";
import { AuthoritativeValue } from "./authoritative-value";

export function RequestSummary({ body }: { body: RequestResponse }) {
  const name = body.resolution.name;
  const hasDetails = Boolean(body.resolution.architecture || body.intent);
  return (
    <section className="panel" aria-labelledby="request-review-heading">
      <h2 id="request-review-heading">{name ?? body.request_id}</h2>
      {name ? <p className="meta">{body.request_id}</p> : null}
      {hasDetails ? (
        <dl>
          {body.resolution.architecture ? (
            <AuthoritativeValue label="Architecture" value={body.resolution.architecture} />
          ) : null}
          {body.intent ? (
            <>
              <AuthoritativeValue label="Workload" value={body.intent.workload_type} />
              <AuthoritativeValue label="Interaction" value={body.intent.interaction_pattern} />
              <div>
                <dt role="term" aria-label="Capabilities">
                  Capabilities
                </dt>
                <dd>{body.intent.capabilities.join(" ")}</dd>
              </div>
            </>
          ) : null}
        </dl>
      ) : null}
      {body.resolution.components && body.resolution.components.length > 0 ? (
        <>
          <h4>Components</h4>
          <ul>
            {body.resolution.components.map((component) => (
              <li key={`${component.role}:${component.name}`}>
                <span>{component.role}</span> <span>{component.name}</span>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}
