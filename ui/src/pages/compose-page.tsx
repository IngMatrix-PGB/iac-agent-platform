import { useEffect, useState } from "react";
import { isUnauthenticated, type ApiClient, type ClientResult } from "../api/client";
import type { RequestListItem, RequestResponse } from "../api/types";
import { ErrorBanner, noticeTone, type NoticeTone } from "../components/error-banner";
import { OpenRequest } from "../components/open-request";
import { RequestForm } from "../components/request-form";
import { chipClass, statusLabel } from "../components/status-label";

const EMPTY_COPY =
  "No indexed requests. A checkpoint created before the durable index can still be opened by request id.";

export function ComposePage({
  client,
  navigate,
  onUnauthenticated,
}: {
  client: ApiClient;
  navigate: (path: string) => void;
  onUnauthenticated?: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState<{ message: string; tone: NoticeTone } | null>(null);
  const [unsaved, setUnsaved] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<RequestResponse | null>(null);
  const [recent, setRecent] = useState<RequestListItem[] | null>(null);
  const [listError, setListError] = useState<{ message: string; tone: NoticeTone } | null>(null);

  useEffect(() => {
    let cancelled = false;
    void client.listRequests().then((result) => {
      if (cancelled) {
        return;
      }
      if (isUnauthenticated(result)) {
        onUnauthenticated?.();
        return;
      }
      if (result.kind === "success") {
        setRecent(result.body.requests);
        setListError(null);
        return;
      }
      setRecent(null);
      setListError(
        result.kind === "network"
          ? { message: result.message, tone: "error" }
          : { message: result.message, tone: noticeTone(result.error) },
      );
    });
    return () => {
      cancelled = true;
    };
  }, [client, onUnauthenticated]);

  async function submit() {
    if (!draft.trim()) {
      setLocalError("Describe the infrastructure before submitting.");
      return;
    }
    setBusy(true);
    setBanner(null);
    setUnsaved(false);
    setLocalError(null);
    setOutcome(null);
    const result = await client.submit(draft);
    setBusy(false);
    applyResult(result);
  }

  function applyResult(result: ClientResult) {
    if (isUnauthenticated(result)) {
      onUnauthenticated?.();
      return;
    }
    if (result.kind === "network" || result.kind === "http") {
      setBanner({
        message: result.message,
        tone: result.kind === "http" ? noticeTone(result.error) : "error",
      });
      setUnsaved(result.kind === "http" && isInterpreterFailure(result.status));
      return;
    }
    if (result.status === 201 && result.body.workflow !== null) {
      navigate(`/requests/${encodeURIComponent(result.body.request_id)}`);
      return;
    }
    setOutcome(result.body);
  }

  return (
    <section id="compose" tabIndex={-1} aria-labelledby="compose-heading">
      <h2 id="compose-heading">New request</h2>
      <p>Describe the infrastructure. A durable workflow opens on its own page.</p>
      <RequestForm value={draft} busy={busy} onChange={setDraft} onSubmit={() => void submit()} />
      <RecentRequests rows={recent} error={listError} navigate={navigate} />
      <h3>Open a saved request</h3>
      <OpenRequest navigate={navigate} />
      {localError ? <p>{localError}</p> : null}
      {banner ? <ErrorBanner message={banner.message} tone={banner.tone} /> : null}
      {unsaved ? <p>This request was not saved.</p> : null}
      {outcome ? <NonDurableOutcome body={outcome} /> : null}
    </section>
  );
}

function RecentRequests({
  rows,
  error,
  navigate,
}: {
  rows: RequestListItem[] | null;
  error: { message: string; tone: NoticeTone } | null;
  navigate: (path: string) => void;
}) {
  return (
    <section id="requests" tabIndex={-1} className="recent-requests" aria-labelledby="recent-requests-heading">
      <h3 id="recent-requests-heading">Recent requests</h3>
      {error ? <ErrorBanner message={error.message} tone={error.tone} /> : null}
      {rows && rows.length === 0 ? <p>{EMPTY_COPY}</p> : null}
      {rows && rows.length > 0 ? (
        <ul>
          {rows.map((row) => {
            const path = `/requests/${encodeURIComponent(row.request_id)}`;
            return (
              <li className="panel catalog-row" key={row.request_id} title={row.created_at}>
                <div>
                  <a
                    href={path}
                    onClick={(event) => {
                      event.preventDefault();
                      navigate(path);
                    }}
                  >
                    {row.name ?? row.request_id}
                  </a>
                  {row.name ? <p className="meta">{row.request_id}</p> : null}
                </div>
                <div>
                  <span className={chipClass(row.workflow_status)} title={row.workflow_status}>
                    {statusLabel(row.workflow_status)}
                  </span>
                  {row.security_status ? (
                    <span className={chipClass(row.security_status)} title={row.security_status}>
                      {statusLabel(row.security_status)}
                    </span>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}

function isInterpreterFailure(status: number): boolean {
  return status === 502 || status === 503 || status === 504;
}

function NonDurableOutcome({ body }: { body: RequestResponse }) {
  const resolution = body.resolution;
  return (
    <section className="panel" aria-labelledby="unsaved-outcome-heading">
      <h3 id="unsaved-outcome-heading">Unsaved result</h3>
      <p>
        <span>Outcome</span> <code>{body.outcome}</code>
      </p>
      <p>This result is not saved. Refreshing clears it.</p>
      {resolution.field ? <p>{resolution.field}</p> : null}
      {resolution.reason ? <p>{resolution.reason}</p> : null}
      {resolution.detail ? <p>{resolution.detail}</p> : null}
      {resolution.allowed_values?.map((value) => (
        <p key={value}>{value}</p>
      ))}
    </section>
  );
}
