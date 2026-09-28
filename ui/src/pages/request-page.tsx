import { useEffect, useState } from "react";
import type { ApiClient, ClientResult } from "../api/client";
import { POLL_INTERVAL_MS, POLL_MAX_ATTEMPTS, shouldPoll } from "../api/polling";
import type { RequestResponse } from "../api/types";
import { ApprovalPanel } from "../components/approval-panel";
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
  const [pollExhausted, setPollExhausted] = useState(false);
  const [seenId, setSeenId] = useState(requestId);

  if (seenId !== requestId) {
    setSeenId(requestId);
    setBody(null);
    setBanner(null);
    setPollExhausted(false);
  }

  useEffect(() => {
    let cancelled = false;
    void client.getRequest(requestId).then((result) => {
      if (!cancelled) {
        applyRead(result);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [client, requestId]);

  const status = body?.workflow?.workflow_status;
  useEffect(() => {
    if (!shouldPoll(status)) {
      return;
    }
    let attempts = 0;
    let stopped = false;
    const timer = window.setInterval(() => {
      attempts += 1;
      if (attempts > POLL_MAX_ATTEMPTS) {
        window.clearInterval(timer);
        setPollExhausted(true);
        return;
      }
      void client.getRequest(requestId).then((result) => {
        if (stopped) {
          return;
        }
        if (result.kind === "network") {
          stopped = true;
          window.clearInterval(timer);
          setBanner(result.message);
          return;
        }
        if (result.kind === "success") {
          setBody(result.body);
          setBanner(null);
          if (!shouldPoll(result.body.workflow?.workflow_status)) {
            stopped = true;
            window.clearInterval(timer);
          }
        }
      });
    }, POLL_INTERVAL_MS);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [client, requestId, status]);

  function applyRead(result: ClientResult) {
    if (result.kind === "success") {
      setBody(result.body);
      setBanner(null);
      return;
    }
    if (result.kind === "http" && result.request) {
      setBody(result.request);
      setBanner(result.message);
      return;
    }
    setBody(null);
    setBanner(result.message);
  }

  function onDecision(result: ClientResult) {
    if (result.kind === "success") {
      setBody(result.body);
      setBanner(null);
      return;
    }
    if (result.kind === "http" && result.request) {
      setBody(result.request);
      setBanner(result.message);
      return;
    }
    setBanner(result.message);
  }

  return (
    <section>
      {banner ? <ErrorBanner message={banner} /> : null}
      {body ? (
        <>
          <RequestSummary body={body} />
          <WorkflowStatus body={body} />
          <PlanSummary plan={body.workflow?.plan ?? null} />
          <Findings findings={body.workflow?.findings ?? []} />
          <ApprovalPanel body={body} client={client} onResult={onDecision} />
        </>
      ) : null}
      {pollExhausted ? (
        <button
          type="button"
          onClick={() => {
            setPollExhausted(false);
            void client.getRequest(requestId).then(applyRead);
          }}
        >
          Refresh
        </button>
      ) : null}
    </section>
  );
}
