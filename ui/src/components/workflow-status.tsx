import type { RequestResponse } from "../api/types";

export function WorkflowStatus({ body }: { body: RequestResponse }) {
  const workflow = body.workflow;
  const pullRequestUrl = workflow?.pull_request?.url;
  return (
    <section>
      {workflow ? <p>{workflow.workflow_status}</p> : null}
      {workflow?.current_stage ? <p>{workflow.current_stage}</p> : null}
      {workflow?.security_status ? <p>{workflow.security_status}</p> : null}
      <p>Terraform apply was not executed.</p>
      <p>{body.approval_available ? "Approval available" : "Approval not available"}</p>
      {workflow?.error ? (
        <>
          <p>{workflow.error.stage}</p>
          <p>{workflow.error.error_type}</p>
        </>
      ) : null}
      {pullRequestUrl ? <a href={pullRequestUrl}>{pullRequestUrl}</a> : null}
    </section>
  );
}
