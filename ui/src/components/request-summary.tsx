import type { RequestResponse } from "../api/types";
import { AuthoritativeValue } from "./authoritative-value";

export function RequestSummary({ body }: { body: RequestResponse }) {
  const architectureMissing = body.resolution.architecture == null;
  const intentMissing = body.intent === null;
  return (
    <section className="panel" aria-labelledby="request-summary-heading">
      <h3 id="request-summary-heading">Request</h3>
      <dl>
        <div>
          <dt role="term" aria-label="Request id">
            Request id
          </dt>
          <dd>
            <code className="enum">{body.request_id}</code>
          </dd>
        </div>
        <AuthoritativeValue label="Outcome" value={body.outcome} />
        {body.resolution.name ? (
          <div>
            <dt role="term" aria-label="Name">
              Name
            </dt>
            <dd>{body.resolution.name}</dd>
          </div>
        ) : null}
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
      {architectureMissing || intentMissing ? <p>Unavailable after reload.</p> : null}
    </section>
  );
}
