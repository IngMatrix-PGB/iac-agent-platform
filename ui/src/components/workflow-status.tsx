import type { RequestResponse } from "../api/types";
import { AuthoritativeValue } from "./authoritative-value";

export function WorkflowStatus({ body }: { body: RequestResponse }) {
  const workflow = body.workflow;
  const pullRequestUrl = workflow?.pull_request?.url;
  return (
    <section className="panel" aria-labelledby="workflow-heading">
      <h3 id="workflow-heading">Workflow</h3>
      {workflow ? (
        <dl>
          <AuthoritativeValue label="Workflow status" value={workflow.workflow_status} />
          {workflow.current_stage ? (
            <AuthoritativeValue label="Stage" value={workflow.current_stage} />
          ) : null}
          {workflow.security_status ? (
            <AuthoritativeValue label="Security status" value={workflow.security_status} />
          ) : null}
        </dl>
      ) : null}
      <p>Terraform apply was not executed.</p>
      {workflow?.error ? (
        <dl>
          {workflow.error.stage !== workflow.current_stage ? (
            <AuthoritativeValue label="Error stage" value={workflow.error.stage} />
          ) : null}
          <AuthoritativeValue label="Error type" value={workflow.error.error_type} />
        </dl>
      ) : null}
      {pullRequestUrl ? (
        <p>
          <span>Pull request</span> <a href={pullRequestUrl}>{pullRequestUrl}</a>
        </p>
      ) : null}
    </section>
  );
}
