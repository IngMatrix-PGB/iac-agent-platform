import { useState } from "react";
import type { ApiClient, ClientResult } from "../api/client";
import type { RequestResponse } from "../api/types";
import { ErrorBanner } from "../components/error-banner";
import { OpenRequest } from "../components/open-request";
import { RequestForm } from "../components/request-form";

export function ComposePage({
  client,
  navigate,
}: {
  client: ApiClient;
  navigate: (path: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
  const [unsaved, setUnsaved] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<RequestResponse | null>(null);

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
    if (result.kind === "network" || result.kind === "http") {
      setBanner(result.message);
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
    <section>
      <RequestForm value={draft} busy={busy} onChange={setDraft} onSubmit={() => void submit()} />
      <OpenRequest navigate={navigate} />
      {localError ? <p>{localError}</p> : null}
      {banner ? <ErrorBanner message={banner} /> : null}
      {unsaved ? <p>This request was not saved.</p> : null}
      {outcome ? <NonDurableOutcome body={outcome} /> : null}
    </section>
  );
}

function isInterpreterFailure(status: number): boolean {
  return status === 502 || status === 503 || status === 504;
}

function NonDurableOutcome({ body }: { body: RequestResponse }) {
  const resolution = body.resolution;
  return (
    <section>
      <h2>{body.outcome}</h2>
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
