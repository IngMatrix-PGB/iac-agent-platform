import { useEffect, useState } from "react";
import type { ApiClient } from "../api/client";
import type { RequestResponse } from "../api/types";
import { ErrorBanner } from "../components/error-banner";
import { Findings } from "../components/findings";
import { PlanSummary } from "../components/plan-summary";
import { RequestSummary } from "../components/request-summary";
import { WorkflowStatus } from "../components/workflow-status";

export function RequestPage({
  client,
  requestId,
}: {
  client: ApiClient;
  requestId: string;
}) {
  const [body, setBody] = useState<RequestResponse | null>(null);
  const [banner, setBanner] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setBody(null);
    setBanner(null);
    void client.getRequest(requestId).then((result) => {
      if (cancelled) {
        return;
      }
      if (result.kind === "success") {
        setBody(result.body);
        return;
      }
      setBanner(result.message);
    });
    return () => {
      cancelled = true;
    };
  }, [client, requestId]);

  return (
    <section>
      {banner ? <ErrorBanner message={banner} /> : null}
      {body ? (
        <>
          <RequestSummary body={body} />
          <WorkflowStatus body={body} />
          <PlanSummary plan={body.workflow?.plan ?? null} />
          <Findings findings={body.workflow?.findings ?? []} />
        </>
      ) : null}
    </section>
  );
}
