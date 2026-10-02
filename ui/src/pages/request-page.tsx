import { useEffect, useState } from "react";
import { isUnauthenticated, type ApiClient, type ClientResult } from "../api/client";
import { POLL_INTERVAL_MS, POLL_MAX_ATTEMPTS, shouldPoll } from "../api/polling";
import type { RequestResponse } from "../api/types";
import { ApprovalPanel } from "../components/approval-panel";
import { ErrorBanner, noticeTone, type NoticeTone } from "../components/error-banner";
import { Findings } from "../components/findings";
import { PlanSummary } from "../components/plan-summary";
import { RequestSummary } from "../components/request-summary";
import { WorkflowStatus } from "../components/workflow-status";

export function RequestPage({
  client,
  requestId,
  onUnauthenticated,
}: {
  client: ApiClient;
  requestId: string;
  onUnauthenticated?: () => void;
}) {
  const [body, setBody] = useState<RequestResponse | null>(null);
  const [banner, setBanner] = useState<{ message: string; tone: NoticeTone } | null>(null);
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
        if (isUnauthenticated(result)) {
          stopped = true;
          window.clearInterval(timer);
          onUnauthenticated?.();
          return;
        }
        if (result.kind === "network") {
          stopped = true;
          window.clearInterval(timer);
          setBanner({ message: result.message, tone: "error" });
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
  }, [client, onUnauthenticated, requestId, status]);

  function noticeFor(result: Exclude<ClientResult, { kind: "success" }>): { message: string; tone: NoticeTone } {
    if (result.kind === "network") {
      return { message: result.message, tone: "error" };
    }
    return { message: result.message, tone: noticeTone(result.error) };
  }

function applyRead(result: ClientResult) {
    if (isUnauthenticated(result)) {
      onUnauthenticated?.();
      return;
    }
    if (result.kind === "success") {
      setBody(result.body);
      setBanner(null);
      return;
    }
    if (result.kind === "http" && result.request) {
      setBody(result.request);
      setBanner(noticeFor(result));
      return;
    }
    setBody(null);
    setBanner(noticeFor(result));
  }

  function onDecision(result: ClientResult) {
    if (isUnauthenticated(result)) {
      onUnauthenticated?.();
      return;
    }
    if (result.kind === "success") {
      setBody(result.body);
      setBanner(null);
      return;
    }
    if (result.kind === "http" && result.request) {
      setBody(result.request);
      setBanner(noticeFor(result));
      return;
    }
    setBanner(noticeFor(result));
  }

  const polling = shouldPoll(status) && !pollExhausted;
  return (
    <section aria-labelledby="request-review-heading">
      <h2 id="request-review-heading">Request review</h2>
      {banner ? <ErrorBanner message={banner.message} tone={banner.tone} /> : null}
      {!body && !banner ? <p role="status">Loading request.</p> : null}
      {polling ? <p role="status">Checking this request.</p> : null}
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
        <>
          <p>Automatic checks stopped.</p>
          <button
            type="button"
            onClick={() => {
              setPollExhausted(false);
              void client.getRequest(requestId).then(applyRead);
            }}
          >
            Refresh
          </button>
        </>
      ) : null}
    </section>
  );
}
