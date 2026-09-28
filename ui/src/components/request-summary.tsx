import type { RequestResponse } from "../api/types";

export function RequestSummary({ body }: { body: RequestResponse }) {
  const architectureMissing = body.resolution.architecture == null;
  const intentMissing = body.intent === null;
  return (
    <section>
      <p>{body.request_id}</p>
      <p>{body.outcome}</p>
      {body.resolution.name ? <p>{body.resolution.name}</p> : null}
      {body.resolution.architecture ? <p>{body.resolution.architecture}</p> : null}
      {body.intent ? (
        <p>
          {body.intent.workload_type} {body.intent.interaction_pattern}{" "}
          {body.intent.capabilities.join(" ")}
        </p>
      ) : null}
      {body.resolution.components?.map((component) => (
        <p key={`${component.role}:${component.name}`}>
          <span>{component.role}</span> <span>{component.name}</span>
        </p>
      ))}
      {architectureMissing || intentMissing ? <p>Unavailable after reload.</p> : null}
    </section>
  );
}
